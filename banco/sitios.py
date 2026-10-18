"""Sitios de referencia del banco.

Cada campo que no viene de una decisión explícita queda listado en
`campos_supuestos`. Esa tupla es el registro de qué hay que preguntarle al
cliente cuando exista, y lo que hay que volver a correr si la respuesta cambia.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .contrato import (
    EtiquetaIntervalo,
    MetadatosSitio,
    PuntoMedicion,
    TipoMontaje,
)

# --------------------------------------------------------------------------
# Planta ficticia de referencia — Medellín
#
# DATO (decidido explícitamente):
#   ubicación, capacidades, inclinación, montaje fijo, resolución de entrega,
#   punto de medición a la salida del inversor.
#
# SUPUESTO (lo declaro yo, no fue decidido):
#   azimut, tipo de montaje, albedo, ventilación posterior, altitud, perfil de
#   horizonte, etiqueta de intervalo, rezago de publicación.
# --------------------------------------------------------------------------

MEDELLIN_REF = MetadatosSitio(
    id="med-ref-500",
    nombre="Planta de referencia Medellín 500 kWp",
    latitud=6.25,
    longitud=-75.57,
    altitud_m=1495.0,
    zona_horaria="America/Bogota",

    capacidad_dc_kwp=500.0,
    capacidad_ac_kw=400.0,
    inclinacion_grados=15.0,
    azimut_grados=180.0,
    tipo_montaje=TipoMontaje.CUBIERTA_PLANA,
    seguidores=False,
    fecha_entrada_operacion=dt.date(2023, 1, 1),

    punto_medicion=PuntoMedicion.INVERSOR_AC,
    etiqueta_intervalo=EtiquetaIntervalo.INICIO,
    resolucion_nativa=pd.Timedelta("5min"),
    rezago_publicacion=pd.Timedelta("6h"),

    albedo=0.15,
    ventilacion_posterior_restringida=True,
    perfil_horizonte=None,  # se define con el escenario; en cubierta urbana no es cero

    fuente_metadatos="especificación del proyecto, 2026-10-17",
    campos_supuestos=(
        "azimut_grados",
        "tipo_montaje",
        "albedo",
        "ventilacion_posterior_restringida",
        "altitud_m",
        "perfil_horizonte",
        "etiqueta_intervalo",
        "rezago_publicacion",
        "fecha_entrada_operacion",
    ),
)

# Gemelo de contraste: misma planta, inclinación alta.
# Existe para separar "el agente no detecta la falla de orientación" de
# "la falla de orientación no es detectable a 15 grados".
MEDELLIN_INCLINADA = MetadatosSitio(
    **{
        **MEDELLIN_REF.__dict__,
        "id": "med-ref-500-i30",
        "nombre": "Gemelo de contraste, inclinación 30°",
        "inclinacion_grados": 30.0,
        "tipo_montaje": TipoMontaje.SUELO,
        "albedo": 0.20,
        "ventilacion_posterior_restringida": False,
    }
)

# Gemelo de contraste para la falla de RECORTE.
# Medido sobre un año sintético, la planta de referencia (DC/AC = 1.25, montaje
# en cubierta con ventilación restringida) recorta el 0.04 % de su energía: la
# falla está presente pero por debajo del umbral de detección. Este gemelo sube
# la razón a 1.40 (1.75 % de energía recortada), que es donde la falla se vuelve
# calificable. Sin él no se puede distinguir "el agente no detectó el recorte"
# de "no había recorte que detectar".
MEDELLIN_RECORTE = MetadatosSitio(
    **{
        **MEDELLIN_REF.__dict__,
        "id": "med-ref-560-dcac140",
        "nombre": "Gemelo de contraste, DC/AC = 1.40",
        "capacidad_dc_kwp": 560.0,
    }
)

SITIOS = {s.id: s for s in (MEDELLIN_REF, MEDELLIN_INCLINADA, MEDELLIN_RECORTE)}
