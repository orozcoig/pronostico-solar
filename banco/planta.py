"""Planta sintética: de clima observado a generación verdadera — Fase 3.1.

Esta es la capa `verdad` del diseño de tres capas. Produce la generación física
sin contaminar: sin artefactos de medición, sin huecos, sin desfases. Las fallas
se inyectan después, y cada una en la capa donde vive físicamente.

Cadena: posición solar -> sombreado de horizonte -> transposición al plano del
arreglo -> IAM -> temperatura de celda -> modelo DC -> pérdidas -> inversor con
recorte duro en la capacidad AC.

Dos decisiones que no son detalle:

  * **Se simula a resolución sub-horaria y se agrega después.** El recorte del
    inversor es un fenómeno sub-horario: una hora cuyo promedio es 350 kW pudo
    haber recortado quince minutos. Simular directo a resolución horaria
    convierte el recorte en un techo plano perfecto, que es trivial de detectar
    y físicamente falso.

  * **El horizonte del escenario limpio NO es cero.** En cubierta urbana del
    Valle de Aburrá hay obstrucción real. Si la línea base fuera horizonte
    plano, la falla de sombreado sería trivial y el banco quedaría optimista.
    La línea base lleva un perfil moderado declarado; la FALLA es una
    desviación respecto de él.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pvlib import iam as pv_iam
from pvlib import inverter, irradiance, pvsystem, temperature
from pvlib.location import Location

from .contrato import DHI, DNI, GHI, POTENCIA_AC, TEMP_AIRE, VIENTO, MetadatosSitio

# Perfil de horizonte moderado para cubierta industrial en valle urbano.
# azimut (grados, 0=N, 90=E) -> elevación obstruida (grados). SUPUESTO declarado.
# Laderas del Aburrá al oriente y occidente, edificación baja al norte y sur.
HORIZONTE_URBANO_MODERADO: dict[float, float] = {
    0: 4.0, 45: 7.0, 90: 11.0, 135: 8.0,
    180: 4.0, 225: 8.0, 270: 12.0, 315: 7.0, 360: 4.0,
}

HORIZONTE_PLANO: dict[float, float] = {0: 0.0, 360: 0.0}


@dataclass(frozen=True)
class ParametrosPlanta:
    """Parámetros de la cadena física. SUPUESTOS salvo donde se indique."""

    gamma_pdc: float = -0.0037        # coef. de potencia, -0.0034 a -0.0040 /°C
    eta_inversor: float = 0.975       # eficiencia nominal del inversor
    perdida_mismatch: float = 0.02
    perdida_cableado_dc: float = 0.015
    perdida_cableado_ac: float = 0.005
    perdida_disponibilidad: float = 0.0   # las paradas van como evento, no como derate
    suciedad_base: float = 0.02       # nivel de ensuciamiento del escenario limpio
    # Límite AC realmente impuesto por el inversor. None = el declarado en
    # metadatos. Que puedan diferir es el punto: una placa dice una cosa y el
    # equipo hace otra, y el modelo hereda la placa.
    limite_ac_real_kw: float | None = None
    # Geometría REALMENTE construida, si difiere de la declarada en metadatos.
    # Que puedan diferir es el punto de la falla de orientación.
    inclinacion_real_grados: float | None = None
    azimut_real_grados: float | None = None
    iam_b0: float = 0.05              # modelo ASHRAE
    horizonte: dict[float, float] = field(default_factory=lambda: dict(HORIZONTE_URBANO_MODERADO))
    # Atenuación de la difusa por la fracción de cielo tapada por el horizonte.
    atenuacion_difusa_horizonte: float = 0.04

    @property
    def derate_dc(self) -> float:
        return (
            (1 - self.perdida_mismatch)
            * (1 - self.perdida_cableado_dc)
            * (1 - self.suciedad_base)
        )


def elevacion_horizonte(azimut_solar: np.ndarray, perfil: dict[float, float]) -> np.ndarray:
    """Interpola el perfil de horizonte al azimut solar instantáneo."""
    xs = np.array(sorted(perfil))
    ys = np.array([perfil[k] for k in xs])
    return np.interp(np.mod(azimut_solar, 360.0), xs, ys)


def simular_generacion(
    meta: MetadatosSitio,
    clima: pd.DataFrame,
    params: ParametrosPlanta | None = None,
    detalle: bool = False,
    suciedad: np.ndarray | None = None,
    disponibilidad: np.ndarray | None = None,
    limite_ac_kw: np.ndarray | None = None,
    capacidad_dc_kwp: np.ndarray | None = None,
) -> pd.DataFrame:
    """Genera la serie de potencia AC verdadera a partir del clima observado.

    `suciedad` es una serie de pérdida fraccional por paso de tiempo; si se omite
    se usa el nivel constante `params.suciedad_base`. Va aquí y no como un
    factor aplicado después porque el ensuciamiento es pérdida física real: el
    inversor ve menos potencia DC, y por lo tanto recorta menos. Aplicarlo sobre
    la salida AC borraría esa interacción, que es justo la que confunde un
    diagnóstico de suciedad con uno de recorte.

    Con `detalle=True` devuelve también POA, temperatura de celda, potencia DC y
    un indicador de recorte. Eso NO se entrega al modelo: existe para calificar
    al agente de diagnóstico contra verdad conocida en la Fase 3.4.
    """
    p = params or ParametrosPlanta()
    # Geometría del ARREGLO (puede diferir de la declarada: falla de orientación).
    # Nombres explícitos: confundir el azimut del arreglo con el del sol es un
    # error silencioso que cambia la energía sin lanzar excepción.
    inclinacion_arr = (
        p.inclinacion_real_grados if p.inclinacion_real_grados is not None else meta.inclinacion_grados
    )
    azimut_arr = p.azimut_real_grados if p.azimut_real_grados is not None else meta.azimut_grados
    t = clima.index
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    pos = sitio.get_solarposition(t)

    cenit = pos["apparent_zenith"].to_numpy()
    azimut_sol = pos["azimuth"].to_numpy()
    elevacion = 90.0 - cenit

    # ---- Sombreado de horizonte: bloquea la DIRECTA, atenúa la difusa.
    # No toca la global medida en plano horizontal: el horizonte afecta lo que
    # llega al arreglo, no lo que registraría un piranómetro de referencia.
    horizonte = elevacion_horizonte(azimut_sol, p.horizonte)
    sombreado = elevacion < horizonte
    dni = np.where(sombreado, 0.0, clima[DNI].to_numpy())
    dhi = clima[DHI].to_numpy() * (1.0 - p.atenuacion_difusa_horizonte)

    # ---- Transposición al plano del arreglo
    dni_extra = irradiance.get_extra_radiation(t)
    poa = irradiance.get_total_irradiance(
        surface_tilt=inclinacion_arr,
        surface_azimuth=azimut_arr,
        solar_zenith=cenit,
        solar_azimuth=azimut_sol,
        dni=dni,
        ghi=clima[GHI].to_numpy(),
        dhi=dhi,
        dni_extra=dni_extra,
        albedo=meta.albedo,
        model="haydavies",
    )

    # ---- Pérdidas por ángulo de incidencia (solo sobre la componente directa)
    aoi = irradiance.aoi(inclinacion_arr, azimut_arr, cenit, azimut_sol)
    f_iam = pv_iam.ashrae(aoi, b=p.iam_b0)
    efectiva = np.clip(
        np.asarray(poa["poa_direct"]) * f_iam + np.asarray(poa["poa_diffuse"]), 0.0, None
    )

    # ---- Temperatura de celda. El montaje decide el juego de parámetros:
    # cubierta con ventilación posterior restringida corre varios grados más
    # caliente que suelo a igual irradiancia, y eso son 1–2 % de energía.
    juego = (
        "close_mount_glass_glass"
        if meta.ventilacion_posterior_restringida
        else "open_rack_glass_glass"
    )
    par_t = temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"][juego]
    t_celda = temperature.sapm_cell(
        poa_global=np.asarray(poa["poa_global"]),
        temp_air=clima[TEMP_AIRE].to_numpy(),
        wind_speed=clima[VIENTO].to_numpy(),
        **par_t,
    )

    # ---- DC, pérdidas, inversor con recorte duro
    perdida_suciedad = p.suciedad_base if suciedad is None else np.asarray(suciedad)
    derate = (1 - p.perdida_mismatch) * (1 - p.perdida_cableado_dc) * (1 - perdida_suciedad)
    pdc = pvsystem.pvwatts_dc(
        effective_irradiance=efectiva,
        temp_cell=t_celda,
        pdc0=(meta.capacidad_dc_kwp if capacidad_dc_kwp is None else np.asarray(capacidad_dc_kwp)) * 1000.0,
        gamma_pdc=p.gamma_pdc,
    ) * derate

    limite_ac = p.limite_ac_real_kw if p.limite_ac_real_kw is not None else meta.capacidad_ac_kw
    if limite_ac_kw is not None:
        # El techo variable entra AQUÍ, dentro del modelo del inversor. Aplicarlo
        # después como un recorte sobre la salida dejaba el inversor limitando
        # en su valor viejo: una ampliación de capacidad producía recorte
        # masivo que nadie había inyectado, y el agente lo diagnosticaba como
        # falla de equipo. El techo que manda es uno solo.
        limite_ac = np.asarray(limite_ac_kw)
    pdc0_inv = limite_ac * 1000.0 / p.eta_inversor
    pac = inverter.pvwatts(pd.Series(pdc, index=t), pdc0=pdc0_inv, eta_inv_nom=p.eta_inversor)
    pac = np.clip(pac.to_numpy(), 0.0, None) * (1 - p.perdida_cableado_ac)

    # Limitación impuesta por el operador: techo VARIABLE en el lado AC. Se
    # aplica después del inversor porque un setpoint de despacho estrangula la
    # salida, no la entrada. Es distinto del recorte por placa, que es fijo.
    # Paradas y mantenimientos: la planta está fuera de servicio. No es un
    # derate: es ausencia de producción, y el día entero queda anómalo.
    if disponibilidad is not None:
        pac = pac * np.asarray(disponibilidad)

    salida = pd.DataFrame({POTENCIA_AC: pac / 1000.0}, index=t)
    if detalle:
        salida["poa_wm2"] = np.asarray(poa["poa_global"])
        salida["poa_efectiva_wm2"] = efectiva
        salida["temp_celda_c"] = t_celda
        salida["potencia_dc_kw"] = pdc / 1000.0
        salida["recortando"] = pdc > pdc0_inv
        salida["suciedad"] = perdida_suciedad
        if disponibilidad is not None:
            salida["disponible"] = np.asarray(disponibilidad)
        salida["sombreado_horizonte"] = sombreado
        salida["elevacion_solar"] = elevacion
    return salida


def a_horario(df: pd.DataFrame, columnas_bool: tuple[str, ...] = ()) -> pd.DataFrame:
    """Agrega a resolución horaria con etiqueta de inicio de intervalo.

    La potencia se promedia (es potencia media del intervalo, no energía). Las
    banderas booleanas se agregan como fracción del intervalo, que es lo que
    permite ver recorte parcial dentro de una hora.
    """
    reglas = {c: ("mean" if c not in columnas_bool else "mean") for c in df.columns}
    return df.resample("1h", label="left", closed="left").agg(reglas)
