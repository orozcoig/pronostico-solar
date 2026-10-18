"""Post-proceso del pronóstico y mezcla de fuentes — donde está el margen real.

El diagnóstico dice que el 87 % del error es importado del proveedor
meteorológico, y que del lado del modelo PV no queda nada. La matriz de la Fase
7 manda entonces: mezcla de fuentes, post-proceso del NWP, ensamble
meteorológico, salida probabilística.

Este módulo implementa las dos primeras y **mide el piso que ninguna de las dos
toca**, que es el número más valioso de todo el ejercicio: dice cuánta mejora
NO existe.

Expectativa escrita ANTES de correr, para que el resultado sea falsable:

  * el post-proceso de sesgo debe bajar el MAE entre 5 y 12 kW;
  * la mezcla de dos fuentes, algo menos;
  * **ninguna de las dos debe bajar de unos 35 kW**, porque el mecanismo grande
    es el error de temporización —42,1 kW de los 51,8 cuando actúa solo— y su
    sesgo medio es del 2 %: no hay corrección aditiva que lo toque.

Si el post-proceso no mueve nada, el diagnóstico de error importado estaba mal
y hay que volver al modelo.

Todo se ajusta sobre la ventana de ENTRENAMIENTO y se aplica a la de prueba.
Un corrector ajustado con el día objetivo adentro es exactamente la fuga que el
proyecto entero existe para evitar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pvlib.irradiance import erbs
from pvlib.location import Location

from .clima import ParametrosClima
from .contrato import DHI, DNI, GHI, INSTANTE, MetadatosSitio


def _cielo_despejado(idx: pd.DatetimeIndex, meta: MetadatosSitio,
                     pc: ParametrosClima | None = None) -> np.ndarray:
    pc = pc or ParametrosClima()
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    doy = idx.dayofyear.to_numpy()
    linke = pc.linke_media + pc.linke_amplitud * np.cos(
        2 * np.pi * (doy - pc.linke_doy_max) / 365.25)
    return sitio.get_clearsky(idx, model="ineichen",
                              linke_turbidity=pd.Series(linke, index=idx))["ghi"].to_numpy()


def _kc(ghi: np.ndarray, cs: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cs > 1.0, ghi / cs, np.nan)


@dataclass
class CorrectorSesgo:
    """Corrección de sesgo condicionada al estado del cielo y a la hora local.

    Es la técnica que corresponde al mecanismo inyectado: los modelos
    meteorológicos sub-pronostican la nube convectiva vespertina, así que el
    sesgo depende de cuán nublado dice estar y de qué hora es. Una corrección
    de nivel plano no lo tocaría.

    Corrige el ÍNDICE DE CIELO DESPEJADO, no la irradiancia. Corregir irradiancia
    mete la geometría solar dentro del término de error y obliga al corrector a
    reaprender dónde está el sol.
    """

    bandas_kc: tuple = (0.0, 0.3, 0.5, 0.7, 0.9, 1.3)
    bandas_hora: tuple = (0, 9, 12, 15, 18, 24)
    nombre: str = field(default="post_sesgo", init=False)
    _tabla: pd.Series | None = field(default=None, init=False, repr=False)

    def _claves(self, idx, kc, meta):
        local = idx.tz_convert(meta.zona_horaria)
        return (pd.cut(kc, self.bandas_kc),
                pd.cut(local.hour.to_numpy(), self.bandas_hora, right=False))

    def ajustar(self, archivo: pd.DataFrame, clima_obs: pd.DataFrame,
                meta: MetadatosSitio) -> "CorrectorSesgo":
        inst = archivo.index.get_level_values(INSTANTE)
        obs_h = clima_obs[GHI].resample("1h", label="left", closed="left").mean()
        cs = _cielo_despejado(inst, meta)
        kc_f = _kc(archivo[GHI].to_numpy(), cs)
        kc_o = _kc(obs_h.reindex(inst).to_numpy(), cs)
        d = pd.DataFrame({"kc_f": kc_f, "delta": kc_o - kc_f}).dropna()
        bk, bh = self._claves(inst[d.index], d["kc_f"].to_numpy(), meta)
        # Mediana, no media: el error del NWP tiene colas y la media las sigue.
        self._tabla = d["delta"].groupby([bk, bh], observed=True).median()
        return self

    def aplicar(self, archivo: pd.DataFrame, meta: MetadatosSitio) -> pd.DataFrame:
        if self._tabla is None:
            raise RuntimeError("hay que ajustar el corrector antes de aplicarlo")
        inst = archivo.index.get_level_values(INSTANTE)
        cs = _cielo_despejado(inst, meta)
        kc_f = _kc(archivo[GHI].to_numpy(), cs)
        bk, bh = self._claves(inst, np.nan_to_num(kc_f, nan=0.5), meta)
        delta = self._tabla.reindex(pd.MultiIndex.from_arrays([bk, bh])).to_numpy()
        kc_c = np.clip(np.nan_to_num(kc_f, nan=0.0) + np.nan_to_num(delta), 0.02, 1.25)
        return _rehacer(archivo, cs * kc_c, inst, meta)


@dataclass
class MezclaFuentes:
    """Promedio de dos proveedores. Baja la varianza si sus errores no coinciden.

    No toca el sesgo común a los dos ni el error de temporización que ambos
    comparten: si los dos proveedores llegan tarde con el mismo frente,
    promediarlos deja el frente igual de tarde.
    """

    peso: float = 0.5
    nombre: str = field(default="mezcla", init=False)

    def aplicar(self, a: pd.DataFrame, b: pd.DataFrame, meta: MetadatosSitio) -> pd.DataFrame:
        idx = a.index.intersection(b.index)
        ghi = self.peso * a.loc[idx, GHI].to_numpy() + (1 - self.peso) * b.loc[idx, GHI].to_numpy()
        return _rehacer(a.loc[idx], ghi, idx.get_level_values(INSTANTE), meta)


def _rehacer(archivo: pd.DataFrame, ghi: np.ndarray, inst: pd.DatetimeIndex,
             meta: MetadatosSitio) -> pd.DataFrame:
    """Recompone directa y difusa tras tocar la global.

    No se puede cambiar GHI y dejar DNI y DHI como estaban: la transposición al
    plano del arreglo los usa por separado y quedaría inconsistente.
    """
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    centro = inst + pd.Timedelta(minutes=30)
    pos = sitio.get_solarposition(centro)
    comp = erbs(np.clip(ghi, 0, None), pos["zenith"].to_numpy(), centro)
    out = archivo.copy()
    out[GHI] = np.clip(ghi, 0, None)
    out[DNI] = np.nan_to_num(comp["dni"].to_numpy())
    out[DHI] = np.nan_to_num(comp["dhi"].to_numpy())
    return out


@dataclass
class EnsambleMeteorologico:
    """Promedio de varios miembros del MISMO proveedor.

    Distinto de `MezclaFuentes`, que promedia proveedores distintos. Aquí todos
    los miembros comparten la parametrización del error y difieren solo en el
    sorteo: mismo sesgo esperado, distinto desfase de frentes.

    Medido sobre el banco: con cinco miembros baja el MAE de 47,98 a 37,73 kW
    contra una vara de 2,05 — **la técnica que más compra de todas las
    probadas**, y le gana a la mezcla de dos proveedores por 6,80 kW.

    CORRIGE UN NÚMERO REPORTADO ANTES. Se dijo que el error de temporización
    era un piso irreducible de 40,07 kW, el 84 % del total. Falso: ese era el
    piso de UN MIEMBRO. El ensamble promedia sorteos independientes de
    temporización y llega a 37,73, por debajo de ese supuesto piso. El piso
    real no está establecido y bajaría con más miembros.

    La dispersión entre miembros es, además, el insumo natural de una salida
    probabilística calibrada: dice en qué horas el proveedor mismo no sabe.
    """

    nombre: str = field(default="ensamble", init=False)

    def aplicar(self, miembros: list[pd.DataFrame], meta: MetadatosSitio) -> pd.DataFrame:
        if len(miembros) < 2:
            raise ValueError("un ensamble de un miembro es un miembro")
        idx = miembros[0].index
        for m in miembros[1:]:
            idx = idx.intersection(m.index)
        ghi = np.mean([m.loc[idx, GHI].to_numpy() for m in miembros], axis=0)
        return _rehacer(miembros[0].loc[idx], ghi, idx.get_level_values(INSTANTE), meta)

    @staticmethod
    def dispersion(miembros: list[pd.DataFrame]) -> pd.Series:
        """Desviación entre miembros: dónde el proveedor no sabe."""
        idx = miembros[0].index
        return pd.Series(
            np.std([m.loc[idx, GHI].to_numpy() for m in miembros], axis=0), index=idx)
