"""Degradador de clima pronosticado — Fase 3.2.

Construye, a partir del clima observado, un archivo de pronóstico con error
realista. Su propósito no es "ensuciar el dato": es permitir medir el **techo
alcanzable** —cuánto del error viene del proveedor meteorológico y cuánto del
modelo PV— contra una degradación de magnitud conocida. En datos reales ese
reparto no se aísla limpiamente; aquí sí, porque nosotros lo inyectamos.

Tres mecanismos independientes y conmutables. Están separados porque **se
corrigen con técnicas distintas**, y meterlos en un solo término de ruido haría
que el agente de diagnóstico nunca pudiera distinguirlos:

  (a) SESGO dependiente del estado. Los modelos meteorológicos sub-pronostican
      la nube convectiva vespertina: en tarde nublada el pronóstico dice que
      hay más sol del que hay. Se corrige con post-proceso del NWP.

  (b) TEMPORIZACIÓN. El episodio nublado existe en el pronóstico pero llega
      tarde o temprano. **La corrección de sesgo no lo arregla**: en promedio
      el sesgo es cero y el error hora a hora es enorme. Se ataca con ensamble
      o con salida probabilística, no con un término aditivo.

  (c) SUAVIZADO + DISPERSIÓN CRECIENTE. Una malla de ~10 km no resuelve una
      nube sobre una planta de 500 kWp: el pronóstico es una versión alisada de
      la verdad, y la dispersión crece con el horizonte. El suavizado es lo que
      produce el síntoma "sobrepronóstico en nublados, subpronóstico en
      despejados" de la Fase 7, por reducción de varianza, no por sesgo.

LIMITACIÓN CONOCIDA DEL DEGRADADOR, medida.
Los miembros de un ensamble generado con este módulo difieren solo por el
sorteo de los mismos mecanismos, así que su dispersión resulta **predecible
desde el propio campo pronosticado**: R² = 0.867 a partir de las features que
el modelo ya tiene, con correlación +0.886 contra la irradiancia en plano y
+0.629 contra el índice de cielo despejado. Consecuencia práctica: **este banco
NO puede evaluar si la dispersión entre miembros mejora la calibración de la
banda**, porque aquí no aporta información que el campo medio no traiga ya.
Medido: agregarla como feature deja la cobertura en 85.7 % y el ancho mediano
en 232 kW contra 234, es decir sin efecto.

En un ensamble real la dispersión sí lleva información independiente sobre la
incertidumbre del régimen —viene de perturbar condiciones iniciales y física,
no de re-sortear un error paramétrico—. Para probar esa técnica habría que
generar miembros con estructuras de error distintas entre sí, no con la misma
parametrización y otra semilla. Queda como trabajo pendiente del banco.

Dos asimetrías deliberadas respecto del observado:

  * El pronóstico es **horario**; la verdad es de 5 minutos. Ningún NWP entrega
    resolución sub-horaria. Un banco que entregue pronóstico a 5 min regala
    información que en operación no existe.
  * El pronóstico se emite en **ciclos** (00 y 12 UTC por defecto) y cubre un
    horizonte fijo. El mismo instante válido aparece varias veces, con distinta
    antigüedad y distinta calidad. Ese es el eje que el esquema de una sola
    fila por instante hace imposible representar.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pvlib.irradiance import erbs
from pvlib.location import Location

from .clima import ParametrosClima
from .contrato import (
    DHI,
    DNI,
    EMITIDO_EN,
    GHI,
    HORIZONTE_H,
    INSTANTE,
    TEMP_AIRE,
    VIENTO,
    MetadatosSitio,
)


@dataclass(frozen=True)
class ParametrosPronostico:
    """Magnitud de cada mecanismo. Todo SUPUESTO; se calibra contra error real."""

    # Ciclos de emisión y alcance
    horas_emision: tuple[int, ...] = (0, 12)   # UTC
    horizonte_max_h: int = 72

    # (a) Sesgo dependiente del estado
    sesgo_activo: bool = True
    sesgo_nublado: float = 0.075      # kc_fc - kc_obs cuando hay nube
    sesgo_despejado: float = 0.005
    sesgo_umbral_kc: float = 0.65     # por debajo cuenta como nublado
    sesgo_refuerzo_convectivo: float = 1.6   # multiplicador en la tarde local
    sesgo_hora_pico: float = 15.0
    sesgo_ancho_h: float = 3.5

    # (b) Temporización
    temporizacion_activa: bool = True
    desfase_sd_h_0: float = 0.45      # desviación del desfase a horizonte 0
    desfase_sd_h_por_dia: float = 0.55  # crecimiento por cada 24 h de horizonte

    # (c) Suavizado y dispersión
    suavizado_activo: bool = True
    suavizado_sigma_h_0: float = 0.8    # kernel gaussiano a horizonte 0
    suavizado_sigma_h_por_dia: float = 0.6
    dispersion_activa: bool = True
    dispersion_kc_0: float = 0.045
    dispersion_kc_por_dia: float = 0.055
    dispersion_phi: float = 0.75        # autocorrelación del error, no ruido blanco

    # Temperatura: error mucho menor que el de nubosidad, y conviene que se note
    sesgo_temp_c: float = -0.3
    dispersion_temp_c_0: float = 0.7
    dispersion_temp_c_por_dia: float = 0.5


def _kernel_gauss(sigma_pasos: float) -> np.ndarray:
    if sigma_pasos <= 0.05:
        return np.array([1.0])
    radio = max(1, int(np.ceil(3 * sigma_pasos)))
    x = np.arange(-radio, radio + 1)
    k = np.exp(-0.5 * (x / sigma_pasos) ** 2)
    return k / k.sum()


def _suavizar_variable(y: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Convolución con kernel de ancho variable. Agrupa por sigma redondeada
    para no convolucionar punto por punto."""
    salida = np.empty_like(y)
    clave = np.round(sigma * 4).astype(int)
    for c in np.unique(clave):
        k = _kernel_gauss(c / 4.0)
        suave = np.convolve(np.pad(y, len(k) // 2, mode="edge"), k, mode="valid")[: len(y)]
        m = clave == c
        salida[m] = suave[m]
    return salida


EPOCA = pd.Timestamp("1970-01-01", tz="UTC")


def _segundos(idx: pd.DatetimeIndex) -> np.ndarray:
    """Segundos desde la época, sin depender de la resolución interna de pandas.

    `idx.view("int64")` devuelve la representación en la unidad interna, que
    cambió de nanosegundos a microsegundos en pandas 3.0. Dividir por 1e9 "porque
    son nanosegundos" produce un desfase silencioso de mil veces. Lo atrapó el
    control del pronóstico perfecto, que debe reproducir la verdad y no lo hacía.
    """
    return (idx - EPOCA).total_seconds().to_numpy(dtype=float)


def _instantes(segundos: np.ndarray) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(EPOCA + pd.to_timedelta(segundos, unit="s"))


def _ar1(n: int, phi: float, rng: np.random.Generator) -> np.ndarray:
    from scipy.signal import lfilter
    e = rng.normal(0.0, np.sqrt(1.0 - phi**2), n)
    e[0] = rng.normal(0.0, 1.0)
    return lfilter([1.0], [1.0, -phi], e)


def generar_archivo_pronostico(
    meta: MetadatosSitio,
    clima_obs: pd.DataFrame,
    valido_desde: dt.datetime,
    valido_hasta: dt.datetime,
    semilla: int = 907,
    params: ParametrosPronostico | None = None,
    params_clima: ParametrosClima | None = None,
) -> pd.DataFrame:
    """Archivo de pronóstico indexado por (emitido_en, instante), horario.

    Devuelve todas las emisiones cuyo horizonte toca la ventana pedida, de modo
    que un mismo instante válido aparece varias veces con distinta antigüedad.
    """
    p = params or ParametrosPronostico()
    pc = params_clima or ParametrosClima()
    rng = np.random.default_rng(semilla)

    desde = pd.Timestamp(valido_desde).tz_convert("UTC")
    hasta = pd.Timestamp(valido_hasta).tz_convert("UTC")

    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)

    # --- kc observado a resolución nativa; es el campo que se degrada.
    doy_obs = clima_obs.index.dayofyear.to_numpy()
    linke_obs = pc.linke_media + pc.linke_amplitud * np.cos(
        2 * np.pi * (doy_obs - pc.linke_doy_max) / 365.25
    )
    cs_obs = sitio.get_clearsky(
        clima_obs.index, model="ineichen", linke_turbidity=pd.Series(linke_obs, index=clima_obs.index)
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        kc_obs = np.where(cs_obs["ghi"].to_numpy() > 1.0,
                          clima_obs[GHI].to_numpy() / cs_obs["ghi"].to_numpy(), np.nan)
    kc_obs = pd.Series(kc_obs, index=clima_obs.index).ffill().bfill().to_numpy()
    seg_obs = _segundos(clima_obs.index)
    temp_obs = clima_obs[TEMP_AIRE].to_numpy()
    viento_obs = clima_obs[VIENTO].to_numpy()

    # --- Emisiones que alcanzan la ventana
    primera = (desde - pd.Timedelta(hours=p.horizonte_max_h)).floor("D")
    candidatas = pd.date_range(primera, hasta, freq="1h", tz="UTC")
    emisiones = candidatas[np.isin(candidatas.hour, p.horas_emision)]

    bloques = []
    for emitido in emisiones:
        validos = pd.date_range(
            emitido + pd.Timedelta(hours=1), emitido + pd.Timedelta(hours=p.horizonte_max_h),
            freq="1h", tz="UTC",
        )
        validos = validos[(validos >= desde) & (validos < hasta)]
        if len(validos) == 0:
            continue
        lead = np.asarray((validos - emitido).total_seconds() / 3600.0, dtype=float)
        dias = lead / 24.0

        # (b) desfase temporal: un solo sorteo por emisión, creciente con el horizonte
        if p.temporizacion_activa:
            sd = p.desfase_sd_h_0 + p.desfase_sd_h_por_dia * dias
            desfase_h = rng.normal(0.0, 1.0) * sd
        else:
            desfase_h = np.zeros(len(validos))

        # Muestreo del kc verdadero sobre el intervalo horario, desplazado.
        # Promediar sub-pasos es lo que convierte potencia instantánea en
        # pronóstico horario, igual que hace un NWP con su paso de integración.
        sub = np.arange(0, 60, 10) * 60.0                      # 6 submuestras por hora
        centros = _segundos(validos)
        objetivo = (centros[:, None] + sub[None, :] - desfase_h[:, None] * 3600.0)
        kc_h = np.interp(objetivo.ravel(), seg_obs, kc_obs).reshape(len(validos), -1).mean(axis=1)
        temp_h = np.interp(centros, seg_obs, temp_obs)
        viento_h = np.interp(centros, seg_obs, viento_obs)

        # (c) suavizado espacial creciente con el horizonte
        if p.suavizado_activo:
            sigma = p.suavizado_sigma_h_0 + p.suavizado_sigma_h_por_dia * dias
            kc_h = _suavizar_variable(kc_h, sigma)

        # (a) sesgo dependiente del estado, reforzado en la tarde convectiva
        if p.sesgo_activo:
            local_h = validos.tz_convert(meta.zona_horaria)
            hl = local_h.hour.to_numpy() + local_h.minute.to_numpy() / 60.0
            refuerzo = 1.0 + (p.sesgo_refuerzo_convectivo - 1.0) * np.exp(
                -(((hl - p.sesgo_hora_pico) / p.sesgo_ancho_h) ** 2)
            )
            nublado = kc_h < p.sesgo_umbral_kc
            kc_h = kc_h + np.where(nublado, p.sesgo_nublado, p.sesgo_despejado) * refuerzo

        # (c) dispersión creciente, autocorrelada
        if p.dispersion_activa:
            sd_kc = p.dispersion_kc_0 + p.dispersion_kc_por_dia * dias
            kc_h = kc_h + sd_kc * _ar1(len(validos), p.dispersion_phi, rng)
            sd_t = p.dispersion_temp_c_0 + p.dispersion_temp_c_por_dia * dias
            temp_h = temp_h + p.sesgo_temp_c + sd_t * _ar1(len(validos), 0.8, rng)

        kc_h = np.clip(kc_h, 0.02, pc.realce_nube_max)

        # El cielo despejado se promedia sobre el MISMO submuestreo horario que
        # kc. Evaluarlo en el instante de etiqueta y multiplicarlo por un kc
        # promediado mezcla una magnitud instantánea con una media de intervalo,
        # y mete un sesgo grande en las horas donde el sol se mueve rápido.
        sub_idx = _instantes((centros[:, None] + sub[None, :]).ravel())
        doy_sub = sub_idx.dayofyear.to_numpy()
        linke_sub = pc.linke_media + pc.linke_amplitud * np.cos(
            2 * np.pi * (doy_sub - pc.linke_doy_max) / 365.25
        )
        cs_sub = sitio.get_clearsky(
            sub_idx, model="ineichen", linke_turbidity=pd.Series(linke_sub, index=sub_idx)
        )
        cs_medio = cs_sub["ghi"].to_numpy().reshape(len(validos), -1).mean(axis=1)
        ghi = np.clip(cs_medio * kc_h, 0.0, None)

        # Geometría al CENTRO del intervalo: es la convención que corresponde a
        # una irradiancia media horaria.
        centro_h = validos + pd.Timedelta(minutes=30)
        pos = sitio.get_solarposition(centro_h)
        comp = erbs(ghi, pos["zenith"].to_numpy(), centro_h)

        idx = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([emitido] * len(validos), tz="UTC"), validos],
            names=[EMITIDO_EN, INSTANTE],
        )
        bloques.append(
            pd.DataFrame(
                {
                    GHI: ghi,
                    DNI: np.nan_to_num(comp["dni"].to_numpy()),
                    DHI: np.nan_to_num(comp["dhi"].to_numpy()),
                    TEMP_AIRE: temp_h,
                    VIENTO: viento_h,
                    HORIZONTE_H: lead,
                },
                index=idx,
            )
        )

    if not bloques:
        return pd.DataFrame(
            columns=[GHI, DNI, DHI, TEMP_AIRE, VIENTO, HORIZONTE_H],
            index=pd.MultiIndex.from_arrays(
                [pd.DatetimeIndex([], tz="UTC"), pd.DatetimeIndex([], tz="UTC")],
                names=[EMITIDO_EN, INSTANTE],
            ),
        )
    return pd.concat(bloques).sort_index()


def pronostico_perfecto(
    meta: MetadatosSitio,
    clima_obs: pd.DataFrame,
    valido_desde: dt.datetime,
    valido_hasta: dt.datetime,
    params: ParametrosPronostico | None = None,
    params_clima: ParametrosClima | None = None,
) -> pd.DataFrame:
    """Archivo con los tres mecanismos apagados: el clima observado, horario.

    Es el experimento del techo alcanzable (primer paso obligatorio de la Fase
    7). La diferencia de error contra el archivo degradado ES el error importado
    del proveedor meteorológico, y aquí su magnitud verdadera se conoce.

    No es un pronóstico. Entrenar con esto y prometer desempeño operativo es la
    fuga más cara del proyecto; se expone con otro nombre a propósito.
    """
    from dataclasses import replace

    base = params or ParametrosPronostico()
    limpio = replace(
        base,
        sesgo_activo=False,
        temporizacion_activa=False,
        suavizado_activo=False,
        dispersion_activa=False,
    )
    return generar_archivo_pronostico(
        meta, clima_obs, valido_desde, valido_hasta, params=limpio, params_clima=params_clima
    )
