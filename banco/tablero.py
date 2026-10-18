"""Tablero de calificación de todos los escenarios. Se publica en el resumen de CI."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .agente import diagnosticar
from .calificacion import calificar, tabla
from .fallas import (
    AmpliacionCapacidad, DesfaseHorario, HuecosYPegados, LimitacionOperador,
    OrientacionDeclarada, ParadasMantenimiento, RecorteInversor, SombreadoHorizonte,
)
from .fuente import FuenteSintetica
from .sitios import MEDELLIN_REF, SITIOS

INI, FIN = dt.date(2023, 1, 1), dt.date(2024, 1, 1)

ESCENARIOS = [
    ("limpio (control 3.5)", MEDELLIN_REF, ()),
    ("desfase_utc", MEDELLIN_REF, (DesfaseHorario(horas=-5.0),)),
    ("desfase_1h_parcial", MEDELLIN_REF, (DesfaseHorario(horas=1.0, desde=dt.date(2023, 7, 1)),)),
    ("paradas", MEDELLIN_REF, (ParadasMantenimiento(
        ventanas=((dt.datetime(2023, 5, 3), dt.datetime(2023, 5, 8)),)),)),
    ("limitacion_operador", MEDELLIN_REF, (LimitacionOperador(),)),
    ("recorte", SITIOS["med-ref-560-dcac140"], (RecorteInversor(),)),
    ("recorte_oculto", SITIOS["med-ref-560-dcac140"], (RecorteInversor(limite_real_kw=340.0),)),
    ("ampliacion", MEDELLIN_REF, (AmpliacionCapacidad(fecha=dt.date(2023, 7, 10)),)),
    ("orientacion", MEDELLIN_REF, (OrientacionDeclarada(azimut_real=215.0),)),
    ("sombreado", MEDELLIN_REF, (SombreadoHorizonte(),)),
    ("huecos_y_pegados", MEDELLIN_REF, (HuecosYPegados(),)),
]


def main() -> None:
    u, v = pd.Timestamp(INI, tz="UTC"), pd.Timestamp(FIN, tz="UTC")
    todo = pd.Timestamp("2099-01-01", tz="UTC")
    cals = []
    for nombre, meta, fallas in ESCENARIOS:
        f = FuenteSintetica(meta, INI, FIN, fallas=fallas)
        h = diagnosticar(f.generacion(u, v, todo), f.clima_observado(u, v), meta,
                         violaciones=f.violaciones_de_contrato())
        cals.append(calificar(nombre, h, f.manifiesto()))
    print("## Tablero de acierto diagnóstico (Fase 3.4 / 3.5)\n")
    print("```")
    print(tabla(cals))
    print("```")


if __name__ == "__main__":
    main()
