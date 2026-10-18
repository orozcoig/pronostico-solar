"""Generador de clima observado sintético — insumo de la Fase 3.1.

El primitivo estocástico es el **índice de cielo despejado** kc = GHI/GHI_cs, no
la nubosidad en porcentaje. Dos razones:

  1. A resolución sub-horaria la distribución de kc en el trópico es *bimodal*:
     o hay sol o hay nube, con pocos valores intermedios. Un modelo de nubosidad
     diaria constante más ruido gaussiano produce una distribución unimodal, y
     con eso la fila "sobrepronóstico en nublados, subpronóstico en despejados"
     de la Fase 7 queda sin caso de prueba.
  2. De kc siempre se deriva una fracción de nube equivalente. Al revés no.

La estructura temporal viene de una cadena de Markov de dos estados (despejado /
cubierto) con un AR(1) latente dentro de cada estado. La cadena produce los
saltos; el AR(1) produce la variación suave mientras el estado se mantiene. Eso
da autocorrelación realista, que es justo lo que el ruido blanco no da y lo que
decide si una planta de 500 kWp es predecible o no.

Estacionalidad bimodal de Medellín: dos máximos de nubosidad al año, centrados
cerca de mediados de abril y mediados de octubre. Modulación diurna convectiva:
la probabilidad de estado cubierto sube en la tarde.

NOTA MEDIDA (no cambiar la cadena a tres estados sin repetir esta medición).
A 5 minutos la distribución de kc sale demasiado bimodal: el valle 0.6–0.9
queda en ~2.7 % de las observaciones diurnas, y el cielo real tiene un tercer
régimen de nube delgada o rota que esta cadena de dos estados no produce. Pero
**al agregar a resolución horaria el valle sube a 24.1 %**, porque dentro de una
hora el cielo cambia de estado y el promedio cae en el medio. Como el pronóstico
es horario y el objetivo es horario, el defecto no se propaga a la escala en que
operan los modelos. Un tercer estado sí haría falta para trabajo sub-horario
(repronóstico intradiario a 5–15 min), y eso lo decide el horizonte de la Fase 1.

Todos los parámetros son SUPUESTOS con rango declarado, no datos. Están en
`ParametrosClima` para que el barrido de sensibilidad sea cambiar un dataclass.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pvlib.irradiance import erbs
from pvlib.location import Location
from scipy import stats

from .contrato import DHI, DNI, GHI, INSTANTE, TEMP_AIRE, VIENTO, MetadatosSitio


@dataclass(frozen=True)
class ParametrosClima:
    """Parámetros del clima sintético. SUPUESTOS, con rango plausible anotado."""

    # --- Turbidez de Linke (atmósfera de fondo). Valle urbano, 1500 m.
    # Rango plausible 3.0–4.8. Se pasa explícita para no depender del archivo
    # de turbidez de pvlib (30 MB) y para que el supuesto quede a la vista.
    linke_media: float = 3.8
    linke_amplitud: float = 0.5
    linke_doy_max: int = 75          # máxima turbidez cerca del final de la seca

    # --- Probabilidad de estado "cubierto"
    p_cubierto_base: float = 0.42    # rango 0.35–0.55 en el Aburrá
    p_cubierto_amplitud: float = 0.16  # amplitud del ciclo BIMODAL
    doy_pico_nubosidad: int = 105    # ~15 abril; el segundo pico cae 182 d después
    convectiva_amplitud: float = 0.22  # cuánto sube P(cubierto) en la tarde
    convectiva_hora_pico: float = 15.0   # hora local
    convectiva_ancho_h: float = 3.5

    # --- Persistencia de la cadena (en pasos de la resolución nativa)
    tau_pasos: float = 14.0          # ~70 min a 5 min; permanencia media realista

    # --- kc dentro de cada estado (Beta reparametrizada por media y dispersión)
    kc_despejado_media: float = 0.97
    kc_despejado_conc: float = 160.0   # concentración alta = poca dispersión
    kc_cubierto_media: float = 0.33
    kc_cubierto_conc: float = 9.0
    phi_ar1: float = 0.88            # autocorrelación del latente dentro del estado
    realce_nube_max: float = 1.12    # tope de realce por borde de nube

    # --- Temperatura del aire (Medellín, ~1500 m)
    t_min_despejado: float = 17.5
    t_min_cubierto: float = 20.0
    t_max_despejado: float = 29.0
    t_max_cubierto: float = 22.5
    hora_t_max: float = 14.0
    ruido_t_sd: float = 0.6

    # --- Viento (para el modelo térmico de celda)
    viento_medio: float = 1.5
    viento_sd: float = 0.7


def _beta_ab(media: float, conc: float) -> tuple[float, float]:
    """Beta reparametrizada: media y concentración -> (a, b)."""
    return media * conc, (1.0 - media) * conc


def _cadena_markov(p_cubierto: np.ndarray, tau: float, rng: np.random.Generator) -> np.ndarray:
    """Cadena de dos estados con probabilidad estacionaria variable en el tiempo.

    Dada la probabilidad objetivo p de estado cubierto y un tiempo de mezcla tau
    en pasos, las transiciones que reproducen esa estacionaria son
    p(despejado->cubierto) = p/tau  y  p(cubierto->despejado) = (1-p)/tau.
    """
    n = len(p_cubierto)
    p01 = np.clip(p_cubierto / tau, 1e-6, 0.9)
    p10 = np.clip((1.0 - p_cubierto) / tau, 1e-6, 0.9)
    u = rng.random(n)
    estado = np.empty(n, dtype=bool)          # True = cubierto
    actual = bool(u[0] < p_cubierto[0])
    for i in range(n):
        actual = (u[i] >= p10[i]) if actual else (u[i] < p01[i])
        estado[i] = actual
    return estado


def _ar1(n: int, phi: float, rng: np.random.Generator) -> np.ndarray:
    """AR(1) estacionario de varianza unitaria, vectorizado por filtro recursivo."""
    from scipy.signal import lfilter
    ruido = rng.normal(0.0, np.sqrt(1.0 - phi**2), n)
    ruido[0] = rng.normal(0.0, 1.0)
    return lfilter([1.0], [1.0, -phi], ruido)


def generar_clima_observado(
    meta: MetadatosSitio,
    inicio: dt.date,
    fin: dt.date,
    semilla: int = 20261017,
    params: ParametrosClima | None = None,
) -> pd.DataFrame:
    """Serie de clima observado a la resolución nativa del sitio.

    Devuelve el contrato de `clima_observado`: índice `instante` tz-aware UTC,
    columnas ghi/dni/dhi/temp_aire/viento. Es la VERDAD meteorológica: el
    pronóstico degradado se construye a partir de ella en el módulo 3.2.
    """
    p = params or ParametrosClima()
    rng = np.random.default_rng(semilla)

    t = pd.date_range(
        pd.Timestamp(inicio, tz="UTC"),
        pd.Timestamp(fin, tz="UTC"),
        freq=meta.resolucion_nativa,
        inclusive="left",
        name=INSTANTE,
    )
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    local = t.tz_convert(meta.zona_horaria)
    doy = t.dayofyear.to_numpy()
    hora_local = local.hour.to_numpy() + local.minute.to_numpy() / 60.0

    # ---- Cielo despejado, con turbidez estacional declarada
    linke = p.linke_media + p.linke_amplitud * np.cos(2 * np.pi * (doy - p.linke_doy_max) / 365.25)
    cs = sitio.get_clearsky(t, model="ineichen", linke_turbidity=pd.Series(linke, index=t))

    # ---- Probabilidad de estado cubierto: bimodal anual x convectiva diurna
    anual = np.cos(4 * np.pi * (doy - p.doy_pico_nubosidad) / 365.25)
    diurna = np.exp(-(((hora_local - p.convectiva_hora_pico) / p.convectiva_ancho_h) ** 2))
    p_cub = np.clip(
        p.p_cubierto_base + p.p_cubierto_amplitud * anual + p.convectiva_amplitud * diurna,
        0.04, 0.96,
    )

    # ---- Cadena de estados + AR(1) latente dentro del estado
    cubierto = _cadena_markov(p_cub, p.tau_pasos, rng)
    z = _ar1(len(t), p.phi_ar1, rng)
    u = stats.norm.cdf(z)                      # latente uniformizado

    a_d, b_d = _beta_ab(p.kc_despejado_media, p.kc_despejado_conc)
    a_c, b_c = _beta_ab(p.kc_cubierto_media, p.kc_cubierto_conc)
    kc = np.where(cubierto, stats.beta.ppf(u, a_c, b_c), stats.beta.ppf(u, a_d, b_d))
    kc = np.clip(np.nan_to_num(kc, nan=0.5), 0.02, p.realce_nube_max)

    ghi = np.clip(cs["ghi"].to_numpy() * kc, 0.0, None)

    # ---- Descomposición a componentes directa y difusa
    pos = sitio.get_solarposition(t)
    comp = erbs(ghi, pos["zenith"].to_numpy(), t)

    # ---- Temperatura del aire, modulada por la nubosidad del día
    dia = pd.Series(cubierto.astype(float), index=t).groupby(t.date).transform("mean").to_numpy()
    t_min = p.t_min_despejado + (p.t_min_cubierto - p.t_min_despejado) * dia
    t_max = p.t_max_despejado + (p.t_max_cubierto - p.t_max_despejado) * dia
    forma = 0.5 * (1.0 - np.cos(2 * np.pi * (hora_local - p.hora_t_max + 12.0) / 24.0))
    temp = t_min + (t_max - t_min) * forma + p.ruido_t_sd * _ar1(len(t), 0.97, rng)

    viento = np.clip(p.viento_medio + p.viento_sd * _ar1(len(t), 0.95, rng), 0.2, None)

    return pd.DataFrame(
        {
            GHI: ghi,
            DNI: np.nan_to_num(comp["dni"].to_numpy()),
            DHI: np.nan_to_num(comp["dhi"].to_numpy()),
            TEMP_AIRE: temp,
            VIENTO: viento,
        },
        index=t,
    )
