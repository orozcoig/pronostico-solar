"""Las tres líneas base de la Fase 5.

Ninguna es persistencia cruda. La persistencia cruda —repetir el día anterior
hora por hora— es trivial de superar en una planta con ciclo diurno marcado: la
gana hasta la climatología. Usarla como referencia infla el valor aparente de
cualquier modelo, y ese valor inflado es lo que después no aparece en operación.

  1. PERSISTENCIA DE ÍNDICE DE CIELO DESPEJADO. Toma la razón entre lo que la
     planta produjo ayer y lo que habría producido con cielo despejado, y la
     aplica al cielo despejado de mañana. Separa "qué tan despejado estuvo" de
     "dónde está el sol", que es lo que la persistencia cruda mezcla.

  2. CLIMATOLOGÍA POR HORA DEL DÍA Y MES. No usa pronóstico. Es el piso: si un
     modelo con pronóstico no le gana, el pronóstico no está aportando nada.

  3. MODELO FÍSICO. Irradiancia pronosticada transpuesta al plano del arreglo
     por un factor de desempeño ajustado sobre la historia. **En sitio único
     suele ser la línea base difícil, y muchas veces gana.** Si el modelo
     aprendido no la supera contra la vara, no hay producto y hay que decirlo.

Interfaz común: `predecir(historia, clima_pron, meta) -> Serie horaria`.
`historia` termina en el corte as-of; `clima_pron` es el pronóstico archivado
del período objetivo. Ninguna línea base ve nada posterior a la emisión.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pvlib.location import Location

from .clima import ParametrosClima
from .contrato import DHI, DNI, GHI, POTENCIA_AC, TEMP_AIRE, VIENTO, MetadatosSitio
from .planta import ParametrosPlanta, simular_generacion


def _clima_cielo_despejado(
    indice: pd.DatetimeIndex, meta: MetadatosSitio, pc: ParametrosClima | None = None
) -> pd.DataFrame:
    """Serie meteorológica de cielo despejado para los instantes dados."""
    pc = pc or ParametrosClima()
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    doy = indice.dayofyear.to_numpy()
    linke = pc.linke_media + pc.linke_amplitud * np.cos(
        2 * np.pi * (doy - pc.linke_doy_max) / 365.25
    )
    cs = sitio.get_clearsky(indice, model="ineichen",
                            linke_turbidity=pd.Series(linke, index=indice))
    # Temperatura típica de día despejado; el modelo térmico la necesita y su
    # efecto de segundo orden no justifica arrastrar una serie real aquí.
    hora = indice.tz_convert(meta.zona_horaria).hour.to_numpy()
    temp = 17.5 + 11.5 * np.clip(np.sin(np.pi * (hora - 6) / 13), 0, None)
    return pd.DataFrame(
        {GHI: cs["ghi"].to_numpy(), DNI: cs["dni"].to_numpy(), DHI: cs["dhi"].to_numpy(),
         TEMP_AIRE: temp, VIENTO: 1.5},
        index=indice,
    )


def _potencia_cielo_despejado(
    indice: pd.DatetimeIndex, meta: MetadatosSitio
) -> pd.Series:
    c = _clima_cielo_despejado(indice, meta)
    c2 = c.copy(); c2.index = c2.index + pd.Timedelta(minutes=30)   # geometría a mitad de hora
    p = simular_generacion(meta, c2)[POTENCIA_AC]
    p.index = indice
    return p


@dataclass
class PersistenciaCieloDespejado:
    """Línea base 1. NO es persistencia cruda; ver el docstring del módulo."""

    dias: int = 1
    nombre: str = field(default="persistencia_kc", init=False)

    def predecir(self, historia, clima_pron, meta) -> pd.Series:
        objetivo = clima_pron.index
        if historia.empty:
            return pd.Series(0.0, index=objetivo)
        corte = historia.index.max() - pd.Timedelta(days=self.dias)
        reciente = historia[historia.index > corte]
        if reciente.empty:
            reciente = historia.tail(24)
        cd_hist = _potencia_cielo_despejado(reciente.index, meta)
        sol = cd_hist > 0.02 * meta.capacidad_ac_kw
        if sol.sum() < 4:
            return pd.Series(0.0, index=objetivo)
        kc = float((reciente[POTENCIA_AC][sol] / cd_hist[sol]).clip(0, 1.2).median())
        return (_potencia_cielo_despejado(objetivo, meta) * kc).clip(lower=0.0)


@dataclass
class ClimatologiaHoraMes:
    """Línea base 2. No usa pronóstico: es el piso que el pronóstico debe superar."""

    nombre: str = field(default="climatologia", init=False)

    def predecir(self, historia, clima_pron, meta) -> pd.Series:
        objetivo = clima_pron.index
        if historia.empty:
            return pd.Series(0.0, index=objetivo)
        local = historia.index.tz_convert(meta.zona_horaria)
        tabla = historia[POTENCIA_AC].groupby([local.month, local.hour]).median()
        lo = objetivo.tz_convert(meta.zona_horaria)
        clave = pd.MultiIndex.from_arrays([lo.month, lo.hour])
        # Si el mes objetivo no está en la historia, se cae a la media por hora:
        # con seis meses de datos, medio año de meses no existe todavía.
        por_hora = historia[POTENCIA_AC].groupby(local.hour).median()
        y = np.array(tabla.reindex(clave).to_numpy(), dtype=float)
        faltan = np.isnan(y)
        if faltan.any():
            y[faltan] = por_hora.reindex(lo.hour[faltan]).to_numpy()
        return pd.Series(np.nan_to_num(y), index=objetivo).clip(lower=0.0)


@dataclass
class ModeloFisico:
    """Línea base 3: la difícil. Transposición al plano del arreglo + factor de
    desempeño ajustado sobre la historia.

    El factor absorbe todo lo que la geometría declarada no explica —suciedad,
    pérdidas reales, error de capacidad— y por eso esta línea base es fuerte.
    Se ajusta solo con historia anterior al corte as-of: un factor ajustado con
    el día objetivo adentro sería fuga.
    """

    ventana_dias: int = 30
    nombre: str = field(default="modelo_fisico", init=False)

    def predecir(self, historia, clima_pron, meta) -> pd.Series:
        objetivo = clima_pron.index
        c = clima_pron.copy()
        c.index = c.index + pd.Timedelta(minutes=30)
        bruto = simular_generacion(meta, c, ParametrosPlanta(suciedad_base=0.0))[POTENCIA_AC]
        bruto.index = objetivo

        factor = 1.0
        if not historia.empty:
            corte = historia.index.max() - pd.Timedelta(days=self.ventana_dias)
            h = historia[historia.index > corte]
            if len(h) > 24:
                cd = _potencia_cielo_despejado(h.index, meta)
                sol = cd > 0.3 * meta.capacidad_ac_kw
                if sol.sum() > 12:
                    # Razón de energías sobre horas de sol alto: robusta a días
                    # nublados, que no informan sobre el factor de desempeño.
                    factor = float(
                        h[POTENCIA_AC][sol].sum() / max(cd[sol].sum(), 1e-9)
                    )
                    factor = float(np.clip(factor / 0.75, 0.6, 1.25))
        return (bruto * factor).clip(lower=0.0)


LINEAS_BASE = (PersistenciaCieloDespejado(), ClimatologiaHoraMes(), ModeloFisico())
