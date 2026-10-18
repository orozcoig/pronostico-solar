"""`FuenteSintetica`: la planta sintética servida a través del contrato — 3.1 + 3.6.

Nada del pipeline llama a `clima.generar_clima_observado` ni a
`planta.simular_generacion` directamente. Todo pasa por aquí, porque el día que
haya un historiador SCADA de un cliente se escribe `FuenteSCADA` con las mismas
cinco funciones y no se toca nada más.

Esta clase es también donde vive el rezago de publicación: `generacion()` corta
en `as_of - rezago`. Que el corte sea una propiedad de la fuente y no una
disciplina del analista es la diferencia entre una regla y un buen propósito.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .clima import ParametrosClima, generar_clima_observado
from .contrato import (
    COLS_CLIMA,
    EMITIDO_EN,
    ContratoViolado,
    POTENCIA_AC,
    MetadatosSitio,
    validar_clima,
    validar_generacion,
)
from .fallas import Capa, Falla
from .planta import ParametrosPlanta, simular_generacion
from .pronostico import (
    ParametrosPronostico,
    generar_archivo_pronostico,
    pronostico_perfecto,
)


class FuenteSintetica:
    """Implementa `FuenteDeDatos` sobre la planta sintética.

    `verdad()` expone la serie sin contaminar y NO es parte del contrato: existe
    solo para calificar al agente de diagnóstico contra verdad conocida (3.4).
    Ninguna ruta de modelado debe llamarla.
    """

    def __init__(
        self,
        meta: MetadatosSitio,
        inicio: dt.date,
        fin: dt.date,
        semilla: int = 20261017,
        params_clima: ParametrosClima | None = None,
        params_planta: ParametrosPlanta | None = None,
        params_pronostico: ParametrosPronostico | None = None,
        fallas: tuple[Falla, ...] = (),
        registro_eventos_disponible: bool = True,
    ) -> None:
        self._meta = meta
        self._inicio, self._fin = inicio, fin
        self._semilla = semilla
        self._p_clima = params_clima or ParametrosClima()
        self._p_planta = params_planta or ParametrosPlanta()
        self._p_pron = params_pronostico or ParametrosPronostico()
        self._registro_eventos_disponible = registro_eventos_disponible

        self._fallas = tuple(fallas)
        self._clima = generar_clima_observado(meta, inicio, fin, semilla, self._p_clima)

        # Capa VERDAD: la falla es pérdida física; entra DENTRO de la cadena.
        p_planta = self._p_planta
        series: dict = {}
        for f in self._fallas:
            if f.capa is Capa.VERDAD:
                p_planta, nuevas = f.modificar_planta(p_planta, self._clima.index, meta)
                for k, v in (nuevas or {}).items():
                    if k == "suciedad" and k in series:
                        # Dos fuentes de pérdida se componen, no se suman.
                        series[k] = 1 - (1 - series[k]) * (1 - v)
                    elif k in ("disponibilidad",) and k in series:
                        series[k] = series[k] * v
                    elif k in ("limite_ac_kw",) and k in series:
                        series[k] = np.minimum(series[k], v)
                    else:
                        series[k] = v
        self._verdad = simular_generacion(
            meta, self._clima, p_planta, detalle=True,
            suciedad=series.get("suciedad"),
            disponibilidad=series.get("disponibilidad"),
            limite_ac_kw=series.get("limite_ac_kw"),
            capacidad_dc_kwp=series.get("capacidad_dc_kwp"),
        )

        # Capa PRONÓSTICO: el insumo meteorológico, ni la planta ni el registro.
        for f in self._fallas:
            if f.capa is Capa.PRONOSTICO:
                self._p_pron = f.modificar_pronostico(self._p_pron)

        # Capa MEDICIÓN: la planta produjo lo que produjo; lo que cambia es el registro.
        self._medicion = self._verdad[[POTENCIA_AC]].copy()
        for f in self._fallas:
            if f.capa is Capa.MEDICION:
                self._medicion = f.modificar_medicion(self._medicion, meta)
        self._medicion = self._medicion.dropna()
        self._eventos = _eventos_vacios()

        validar_clima(self._clima, "clima sintético")
        # Una serie CON falla inyectada puede violar el contrato a propósito:
        # una ampliación de capacidad produce potencia por encima de la placa
        # declarada, y eso no es un error del banco sino la firma de la falla.
        # La violación se registra en vez de abortar, y el agente la consume
        # como evidencia de primera clase: es más directa que cualquier índice
        # derivado. Sobre el escenario limpio la validación sigue siendo dura.
        self._violaciones: list[str] = []
        try:
            validar_generacion(self._medicion, meta, "generación sintética")
        except ContratoViolado as e:
            if not self._fallas:
                raise
            self._violaciones.append(str(e))

    # -- contrato -----------------------------------------------------------

    def metadatos_sitio(self) -> MetadatosSitio:
        return self._meta

    def generacion(
        self, inicio: dt.datetime, fin: dt.datetime, as_of: dt.datetime
    ) -> pd.DataFrame:
        corte = pd.Timestamp(as_of) - self._meta.rezago_publicacion
        ventana = self._medicion.loc[pd.Timestamp(inicio) : pd.Timestamp(fin)]
        return ventana[ventana.index < corte].copy()

    def clima_observado(self, inicio: dt.datetime, fin: dt.datetime) -> pd.DataFrame:
        return self._clima.loc[pd.Timestamp(inicio) : pd.Timestamp(fin), COLS_CLIMA].copy()

    def clima_pronosticado(
        self,
        valido_desde: dt.datetime,
        valido_hasta: dt.datetime,
        emitido_en: dt.datetime | None = None,
    ) -> pd.DataFrame:
        arch = generar_archivo_pronostico(
            self._meta, self._clima, valido_desde, valido_hasta,
            semilla=self._semilla + 1, params=self._p_pron, params_clima=self._p_clima,
        )
        if emitido_en is None:
            return arch
        return arch.xs(pd.Timestamp(emitido_en), level=EMITIDO_EN, drop_level=False).copy()

    # -- fuera del contrato: experimento del techo alcanzable ---------------

    def clima_como_si_fuera_perfecto(
        self, valido_desde: dt.datetime, valido_hasta: dt.datetime
    ) -> pd.DataFrame:
        """Archivo con los tres mecanismos apagados. NO es un pronóstico.

        Existe solo para el primer experimento de la Fase 7: separar el error
        importado del meteorológico del error propio del modelo PV.
        """
        return pronostico_perfecto(
            self._meta, self._clima, valido_desde, valido_hasta,
            params=self._p_pron, params_clima=self._p_clima,
        )

    def eventos(self, inicio: dt.datetime, fin: dt.datetime) -> pd.DataFrame:
        """Vacío porque el escenario limpio no tiene eventos.

        Distinto de no tener registro: eso lo dice
        `registro_eventos_disponible`, no el DataFrame vacío.
        """
        if not self._registro_eventos_disponible:
            raise RuntimeError(
                "Este escenario simula un cliente SIN registro de eventos. "
                "Un día anómalo aquí es un hueco de información, no una señal."
            )
        e = self._eventos
        return e[(e["fin"] >= pd.Timestamp(inicio)) & (e["inicio"] <= pd.Timestamp(fin))].copy()

    # -- fuera del contrato, solo para calificar al agente -------------------

    def verdad(self) -> pd.DataFrame:
        """Serie física sin contaminar, con detalle. NO usar para modelar."""
        return self._verdad.copy()

    def violaciones_de_contrato(self) -> list[str]:
        """Lo que el validador rechazó. Vacío sobre datos sanos."""
        return list(self._violaciones)

    def manifiesto(self) -> dict:
        """Qué se inyectó y con qué magnitud. Es la verdad que califica al agente.

        Un escenario sin fallas devuelve la lista vacía, y esa es la respuesta
        correcta del control negativo de la Fase 3.5.
        """
        return {
            "sitio": self._meta.id,
            "ventana": [str(self._inicio), str(self._fin)],
            "semilla": self._semilla,
            "n_fallas": len(self._fallas),
            "fallas": [f.manifiesto() for f in self._fallas],
        }


def _eventos_vacios() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "inicio": pd.Series(dtype="datetime64[ns, UTC]"),
            "fin": pd.Series(dtype="datetime64[ns, UTC]"),
            "tipo": pd.Series(dtype="object"),
            "magnitud": pd.Series(dtype="float64"),
            "origen": pd.Series(dtype="object"),
            "nota": pd.Series(dtype="object"),
        }
    )
