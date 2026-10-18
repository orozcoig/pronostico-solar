"""Contrato de la interfaz de datos del banco de pruebas — Fase 3.6.

Todo lo que consume datos en este proyecto (generador sintético, agente de
diagnóstico, modelos, evaluación) lee a través de `FuenteDeDatos`. Pasar de
planta sintética a medición real debe ser *cambiar la implementación*, no
reescribir el código que la consume.

Cuatro invariantes. No son estilo: cada una cierra una fuga concreta.

  I1 — Todo instante es tz-aware en UTC dentro del pipeline. La conversión a
       hora local ocurre solo en los bordes (lectura de la fuente, impresión).
       Los desfases legítimos en Colombia son discretos y conocidos: 5 h
       exactas (no hay horario de verano), 1 h por etiqueta de inicio contra
       etiqueta de fin, y la numeración 1–24 de XM contra 0–23. Cualquier otro
       valor es otra cosa, y hay que investigarlo en vez de corregirlo.

  I2 — `as_of` es obligatorio en la firma de `generacion()`. Si se puede
       omitir, se omitirá, y la fuga entra sin que nadie la note. Devuelve
       únicamente lo que estaba disponible en ese instante de emisión.

  I3 — El clima pronosticado se indexa por (emitido_en, instante). Una sola
       fila por instante válido ya asume un único horizonte de emisión, y eso
       hace imposible cumplir la regla de entrenar con el pronóstico archivado
       que existía en su momento.

  I4 — Las convenciones se declaran en metadatos; el código nunca las adivina.
       Unidades, etiqueta de intervalo, punto de medición y resolución nativa
       vienen de la fuente. Un validador no puede distinguir etiqueta-inicio de
       etiqueta-fin: solo el ancla de mediodía solar puede, y eso es Fase 4.

La potencia va en kW (promedio sobre el intervalo), nunca en kWh. La energía es
derivable multiplicando por la duración; al revés hay que conocer la duración,
y eso convierte cada remuestreo en una oportunidad de equivocarse.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

import pandas as pd

# --------------------------------------------------------------------------
# Nombres de columna. Centralizados para que un cambio de esquema sea un
# cambio en un solo sitio y no una cacería de strings.
# --------------------------------------------------------------------------

INSTANTE = "instante"          # inicio del intervalo, tz-aware UTC
EMITIDO_EN = "emitido_en"      # instante de emisión del pronóstico, tz-aware UTC
HORIZONTE_H = "horizonte_h"    # derivado: (instante - emitido_en) en horas

POTENCIA_AC = "potencia_ac_kw"   # promedio sobre el intervalo
GHI = "ghi_wm2"
DNI = "dni_wm2"
DHI = "dhi_wm2"
TEMP_AIRE = "temp_aire_c"
VIENTO = "viento_ms"

COLS_GENERACION = [POTENCIA_AC]
COLS_CLIMA = [GHI, DNI, DHI, TEMP_AIRE, VIENTO]
COLS_CLIMA_MINIMAS = [GHI, TEMP_AIRE]


# --------------------------------------------------------------------------
# Convenciones declaradas
# --------------------------------------------------------------------------

class EtiquetaIntervalo(Enum):
    """Qué extremo del intervalo nombra la marca de tiempo."""
    INICIO = "inicio"
    FIN = "fin"


class PuntoMedicion(Enum):
    """Dónde se mide. Decide qué pérdidas están dentro del objetivo."""
    DC = "dc"                              # entrada del inversor
    INVERSOR_AC = "inversor_ac"            # salida del inversor, generación bruta
    FRONTERA_COMERCIAL = "frontera"        # medidor de frontera, neta


class TipoMontaje(Enum):
    SUELO = "suelo"
    CUBIERTA_PLANA = "cubierta_plana"
    CUBIERTA_INCLINADA = "cubierta_inclinada"


class TipoEvento(Enum):
    PARADA = "parada"              # planta fuera de servicio
    LIMITACION = "limitacion"      # techo impuesto por el operador
    LAVADO = "lavado"              # limpieza de módulos
    MANTENIMIENTO = "mantenimiento"
    AMPLIACION = "ampliacion"      # cambio de capacidad instalada


class OrigenEvento(Enum):
    """Un evento declarado por el cliente y uno inferido del dato no valen igual.

    Mezclarlos es la forma más fácil de convertir una hipótesis del analista en
    un hecho del expediente.
    """
    DECLARADO = "declarado"
    INFERIDO = "inferido"


# --------------------------------------------------------------------------
# Metadatos del sitio
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MetadatosSitio:
    """Todo lo que el pipeline necesita saber del sitio y que no es serie de tiempo.

    Campos sin valor por defecto: no hay default defendible y adivinarlos es
    exactamente el error que este contrato existe para prevenir.
    """

    # Identidad y geografía
    id: str
    nombre: str
    latitud: float
    longitud: float
    altitud_m: float
    zona_horaria: str                 # IANA, p. ej. "America/Bogota"

    # Planta
    capacidad_dc_kwp: float
    capacidad_ac_kw: float
    inclinacion_grados: float
    azimut_grados: float              # 180 = sur geográfico
    tipo_montaje: TipoMontaje
    seguidores: bool
    fecha_entrada_operacion: dt.date

    # Convenciones del dato — I4
    punto_medicion: PuntoMedicion
    etiqueta_intervalo: EtiquetaIntervalo
    resolucion_nativa: pd.Timedelta
    rezago_publicacion: pd.Timedelta  # cuánto tarda el dato en estar disponible

    # Parámetros físicos con default declarado pero revisable
    albedo: float = 0.15
    ventilacion_posterior_restringida: bool = False
    perfil_horizonte: dict[float, float] | None = None  # azimut -> elevación (grados)

    # Procedencia y supuestos. Separar dato de supuesto empieza aquí.
    fuente_metadatos: str = "no declarada"
    campos_supuestos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def razon_dc_ac(self) -> float:
        return self.capacidad_dc_kwp / self.capacidad_ac_kw

    def es_supuesto(self, campo: str) -> bool:
        return campo in self.campos_supuestos

    def __post_init__(self) -> None:
        if not -90 <= self.latitud <= 90:
            raise ValueError(f"latitud fuera de rango: {self.latitud}")
        if not -180 <= self.longitud <= 180:
            raise ValueError(f"longitud fuera de rango: {self.longitud}")
        if not 0 <= self.inclinacion_grados <= 90:
            raise ValueError(f"inclinación fuera de rango: {self.inclinacion_grados}")
        if not 0 <= self.azimut_grados < 360:
            raise ValueError(f"azimut fuera de rango: {self.azimut_grados}")
        if self.capacidad_ac_kw <= 0 or self.capacidad_dc_kwp <= 0:
            raise ValueError("las capacidades deben ser positivas")
        if self.resolucion_nativa <= pd.Timedelta(0):
            raise ValueError("la resolución nativa debe ser positiva")
        for campo in self.campos_supuestos:
            if not hasattr(self, campo):
                raise ValueError(f"campo supuesto inexistente: {campo}")


# --------------------------------------------------------------------------
# La interfaz
# --------------------------------------------------------------------------

@runtime_checkable
class FuenteDeDatos(Protocol):
    """La única puerta de entrada de datos al pipeline.

    Protocol estructural a propósito: una implementación no tiene que heredar
    de nada, solo cumplir las firmas. Eso permite envolver un historiador SCADA
    de un cliente sin tocar su código.
    """

    def metadatos_sitio(self) -> MetadatosSitio:
        ...

    def generacion(
        self,
        inicio: dt.datetime,
        fin: dt.datetime,
        as_of: dt.datetime,
    ) -> pd.DataFrame:
        """Generación medida, tal como estaba disponible en `as_of`.

        `as_of` no es opcional (I2). La implementación debe aplicar el rezago de
        publicación declarado en metadatos y devolver solo lo que ya existía.
        Un `as_of` en el futuro respecto de `fin` no es error: significa que ya
        pasó todo el rezago.

        Índice: `instante`, tz-aware UTC, ordenado, sin duplicados.
        Columnas: `potencia_ac_kw`. NaN representa hueco de medición, y es
        información: no se rellena aquí.
        """
        ...

    def clima_observado(self, inicio: dt.datetime, fin: dt.datetime) -> pd.DataFrame:
        """Clima observado o reanálisis.

        Sirve para UN solo propósito legítimo: medir el techo alcanzable
        (primer experimento de la Fase 7). Entrenar un modelo operativo con esto
        y prometer su desempeño es la fuga más cara del proyecto.

        Índice: `instante`, tz-aware UTC. Columnas: ver COLS_CLIMA.
        """
        ...

    def clima_pronosticado(
        self,
        valido_desde: dt.datetime,
        valido_hasta: dt.datetime,
        emitido_en: dt.datetime | None = None,
    ) -> pd.DataFrame:
        """Pronóstico archivado tal como fue emitido (I3).

        Con `emitido_en=None` devuelve todas las emisiones que cubren la
        ventana; con un valor, solo esa corrida. Devolver varias emisiones es lo
        normal: el horizonte es un eje del problema, no un parámetro fijo.

        Índice: MultiIndex (`emitido_en`, `instante`), ambos tz-aware UTC.
        Columnas: ver COLS_CLIMA, más `horizonte_h`.
        """
        ...

    def eventos(self, inicio: dt.datetime, fin: dt.datetime) -> pd.DataFrame:
        """Paradas, limitaciones, lavados, ampliaciones.

        Devolver un DataFrame vacío es una respuesta válida y significativa: el
        cliente que no lleva registro de paradas tiene un diagnóstico más
        difícil, y eso se cotiza distinto. Vacío no es lo mismo que "no hubo".

        Columnas: inicio, fin, tipo (TipoEvento), magnitud, origen (OrigenEvento),
        nota.
        """
        ...


# --------------------------------------------------------------------------
# Validadores
# --------------------------------------------------------------------------

class ContratoViolado(ValueError):
    """La fuente devolvió algo que no cumple el contrato."""


def _exigir_indice_utc(df: pd.DataFrame, nombre: str, columna: str = INSTANTE) -> None:
    idx = df.index.get_level_values(columna) if isinstance(df.index, pd.MultiIndex) else df.index
    if idx.name != columna:
        raise ContratoViolado(f"{nombre}: el índice debe llamarse '{columna}', no '{idx.name}'")
    if not isinstance(idx, pd.DatetimeIndex):
        raise ContratoViolado(f"{nombre}: el índice '{columna}' debe ser DatetimeIndex")
    if idx.tz is None:
        raise ContratoViolado(
            f"{nombre}: índice sin zona horaria. Un instante naive en este dominio "
            f"es una falla de 5 horas esperando a ocurrir (I1)."
        )
    if str(idx.tz) not in ("UTC", "utc"):
        raise ContratoViolado(f"{nombre}: el índice debe estar en UTC, no en {idx.tz} (I1)")


def _exigir_columnas(df: pd.DataFrame, cols: list[str], nombre: str) -> None:
    faltan = [c for c in cols if c not in df.columns]
    if faltan:
        raise ContratoViolado(f"{nombre}: faltan columnas {faltan}")


def validar_generacion(df: pd.DataFrame, meta: MetadatosSitio, nombre: str = "generacion") -> None:
    _exigir_indice_utc(df, nombre)
    _exigir_columnas(df, COLS_GENERACION, nombre)
    if not df.index.is_monotonic_increasing:
        raise ContratoViolado(f"{nombre}: índice no ordenado")
    if df.index.has_duplicates:
        raise ContratoViolado(f"{nombre}: índice con duplicados")

    p = df[POTENCIA_AC]
    # Tolerancia del 5 %: el inversor puede entregar algo por encima de placa en
    # condiciones frías. Más que eso es error de unidades o de metadatos.
    if meta.punto_medicion is PuntoMedicion.INVERSOR_AC:
        techo = meta.capacidad_ac_kw * 1.05
        exceso = p[p > techo]
        if len(exceso):
            raise ContratoViolado(
                f"{nombre}: {len(exceso)} valores por encima de {techo:.0f} kW "
                f"(máx {exceso.max():.0f}). Revise unidades o capacidad_ac_kw "
                f"antes de tratarlo como dato."
            )
    if (p.dropna() < -0.01 * meta.capacidad_ac_kw).any():
        raise ContratoViolado(
            f"{nombre}: potencia negativa relevante con punto_medicion="
            f"{meta.punto_medicion.value}. Solo es esperable en FRONTERA_COMERCIAL."
        )


def validar_clima(df: pd.DataFrame, nombre: str = "clima", minimas: bool = False) -> None:
    _exigir_indice_utc(df, nombre)
    _exigir_columnas(df, COLS_CLIMA_MINIMAS if minimas else COLS_CLIMA, nombre)
    if GHI in df and (df[GHI].dropna() < 0).any():
        raise ContratoViolado(f"{nombre}: irradiancia negativa")
    if GHI in df and (df[GHI].dropna() > 1500).any():
        raise ContratoViolado(f"{nombre}: GHI > 1500 W/m², revise unidades")


def validar_pronostico(df: pd.DataFrame, nombre: str = "pronostico") -> None:
    if not isinstance(df.index, pd.MultiIndex) or list(df.index.names) != [EMITIDO_EN, INSTANTE]:
        raise ContratoViolado(
            f"{nombre}: el índice debe ser MultiIndex ({EMITIDO_EN}, {INSTANTE}). "
            f"Una fila por instante válido asume un horizonte único (I3)."
        )
    _exigir_indice_utc(df, nombre, EMITIDO_EN)
    _exigir_indice_utc(df, nombre, INSTANTE)
    _exigir_columnas(df, COLS_CLIMA_MINIMAS + [HORIZONTE_H], nombre)
    emitido = df.index.get_level_values(EMITIDO_EN)
    instante = df.index.get_level_values(INSTANTE)
    if (instante < emitido).any():
        raise ContratoViolado(
            f"{nombre}: hay filas válidas ANTES de su emisión. Eso es un pronóstico "
            f"del pasado y no existe en operación."
        )


# --------------------------------------------------------------------------
# Normalización de etiqueta de intervalo
# --------------------------------------------------------------------------

def alinear_a_inicio(df: pd.DataFrame, meta: MetadatosSitio) -> pd.DataFrame:
    """Lleva el índice a convención etiqueta-inicio usando lo declarado en metadatos.

    Esta función cierra la trampa de 1 hora *si los metadatos son correctos*.
    No puede detectar una declaración equivocada: ningún validador puede. Eso
    solo lo resuelve el ancla de mediodía solar, en Fase 4.
    """
    if meta.etiqueta_intervalo is EtiquetaIntervalo.INICIO:
        return df
    salida = df.copy()
    salida.index = salida.index - meta.resolucion_nativa
    salida.index.name = INSTANTE
    return salida


__all__ = [
    "INSTANTE", "EMITIDO_EN", "HORIZONTE_H", "POTENCIA_AC",
    "GHI", "DNI", "DHI", "TEMP_AIRE", "VIENTO",
    "COLS_GENERACION", "COLS_CLIMA", "COLS_CLIMA_MINIMAS",
    "EtiquetaIntervalo", "PuntoMedicion", "TipoMontaje", "TipoEvento", "OrigenEvento",
    "MetadatosSitio", "FuenteDeDatos", "ContratoViolado",
    "validar_generacion", "validar_clima", "validar_pronostico", "alinear_a_inicio",
]
