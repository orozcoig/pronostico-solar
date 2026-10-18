"""Potencia diagnóstica contra longitud de serie — entregable de la Etapa 1.

Responde la pregunta que un cliente hace primero: *con la historia que tengo,
¿qué se puede diagnosticar y qué no?* La respuesta no es una opinión: es esta
tabla, medida sobre fallas de magnitud conocida.

Para cada ventana se corre el agente completo sobre cada escenario y se marca:

    ok    el agente identificó la falla inyectada y no inventó ninguna
    FALTA no la identificó (falso negativo)
    FP    la identificó pero además inventó otra (falso positivo)
    FP!   ni la identificó e inventó otra

Sobre el escenario limpio la única marca aprobatoria es `ok` con cero hallazgos:
ahí la tabla mide la tasa de falsos positivos como función de la historia
disponible, que es lo que decide si un diagnóstico corto es honesto o es ruido.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .agente import diagnosticar
from .calificacion import calificar
from .fallas import (
    AmpliacionCapacidad,
    DerivaSuciedad,
    DesfaseHorario,
    HuecosYPegados,
    LimitacionOperador,
    OrientacionDeclarada,
    ParadasMantenimiento,
    RecorteInversor,
    SombreadoHorizonte,
)
from .fuente import FuenteSintetica
from .sitios import MEDELLIN_REF, SITIOS

INICIO = dt.date(2022, 1, 1)
MESES = (6, 12, 18, 24, 36)


def _fin(meses: int) -> dt.date:
    return (pd.Timestamp(INICIO) + pd.DateOffset(months=meses)).date()


def escenarios(inicio: dt.date, fin: dt.date):
    """Las fallas con fecha se reubican proporcionalmente a la ventana.

    Si no, una ventana de seis meses no alcanzaría a contener el evento y la
    tabla mediría la ubicación del evento en vez de la potencia del detector.
    """
    medio = inicio + (fin - inicio) / 2
    cuarto = inicio + (fin - inicio) / 4
    meses = round((fin - inicio).days / 30.44)
    lavados = tuple(
        (pd.Timestamp(inicio) + pd.DateOffset(months=k)).date()
        for k in range(6, meses, 6)
    )
    return [
        ("limpio (control)", MEDELLIN_REF, ()),
        ("desfase_parcial", MEDELLIN_REF, (DesfaseHorario(horas=1.0, desde=medio),)),
        ("paradas", MEDELLIN_REF, (ParadasMantenimiento(ventanas=(
            (dt.datetime.combine(cuarto, dt.time()),
             dt.datetime.combine(cuarto + dt.timedelta(days=5), dt.time())),)),)),
        ("limitacion_operador", MEDELLIN_REF, (LimitacionOperador(),)),
        ("recorte", SITIOS["med-ref-560-dcac140"], (RecorteInversor(),)),
        ("ampliacion", MEDELLIN_REF, (AmpliacionCapacidad(fecha=medio),)),
        ("orientacion", MEDELLIN_REF, (OrientacionDeclarada(azimut_real=215.0),)),
        ("sombreado", MEDELLIN_REF, (SombreadoHorizonte(),)),
        ("huecos_y_pegados", MEDELLIN_REF, (HuecosYPegados(),)),
        ("suciedad", MEDELLIN_REF, (DerivaSuciedad(tasa_mensual=0.006, lavados=lavados),)),
    ]


def marca(c) -> str:
    if c.aprueba:
        return "ok"
    if c.faltantes and c.falsos_positivos:
        return "FP!"
    if c.faltantes:
        return "FALTA"
    return "FP"


def correr(meses_lista=MESES) -> pd.DataFrame:
    filas: dict[str, dict[int, str]] = {}
    for meses in meses_lista:
        fin = _fin(meses)
        u, v = pd.Timestamp(INICIO, tz="UTC"), pd.Timestamp(fin, tz="UTC")
        todo = pd.Timestamp("2099-01-01", tz="UTC")
        for nombre, meta, fallas in escenarios(INICIO, fin):
            f = FuenteSintetica(meta, INICIO, fin, fallas=fallas)
            h = diagnosticar(f.generacion(u, v, todo), f.clima_observado(u, v), meta,
                             violaciones=f.violaciones_de_contrato())
            filas.setdefault(nombre, {})[meses] = marca(
                calificar(nombre, h, f.manifiesto())
            )
    return pd.DataFrame(filas).T.reindex(columns=list(meses_lista))


def main() -> None:
    t = correr()
    print("## Potencia diagnóstica vs. meses de historia\n")
    print("```")
    print(t.to_string())
    print("```")


if __name__ == "__main__":
    main()
