"""Arnés de backtest operativo — reproduce el momento de emisión, no el archivo.

Para cada día objetivo se fija una hora de emisión, se pide a la fuente **solo
lo que existía en ese instante** (`as_of`) y el pronóstico archivado **emitido
en ese instante**. Ningún modelo ve nada posterior.

Dos cosas que este arnés hace y un `train_test_split` no:

  * Aplica el rezago de publicación. La generación de ayer puede no estar
    disponible todavía al emitir; el modelo tiene que vivir con eso.
  * Usa el pronóstico de la corrida correspondiente, no el mejor disponible
    después. Entrenar o evaluar con una corrida posterior es la fuga más cara
    del proyecto, y aquí es imposible por construcción: la fuente indexa el
    archivo por instante de emisión.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .contrato import COLS_CLIMA, EMITIDO_EN, HORIZONTE_H, INSTANTE, POTENCIA_AC


def _dias(inicio: dt.date, fin: dt.date) -> list[dt.date]:
    return [d.date() for d in pd.date_range(inicio, fin, freq="D", inclusive="left")]


def correr(
    fuente,
    meta,
    modelos: dict,
    inicio: dt.date,
    fin: dt.date,
    hora_emision_utc: int = 12,
) -> pd.DataFrame:
    """Devuelve predicciones horarias por modelo y la generación real.

    Columnas: una por modelo, más `real`. Índice horario tz-aware UTC.
    """
    verdad = (
        fuente.verdad()[POTENCIA_AC]
        .resample("1h", label="left", closed="left")
        .mean()
        .rename("real")
    )
    # El archivo de pronóstico se genera UNA vez para toda la ventana y se
    # rebana por emisión: regenerarlo por día multiplicaría el costo sin
    # cambiar nada, porque cada emisión es independiente.
    archivo = fuente.clima_pronosticado(
        pd.Timestamp(inicio, tz="UTC"), pd.Timestamp(fin, tz="UTC") + pd.Timedelta(days=1)
    )

    bloques = []
    for dia in _dias(inicio, fin):
        emision = pd.Timestamp(dia, tz="UTC") - pd.Timedelta(days=1) + pd.Timedelta(
            hours=hora_emision_utc
        )
        if emision not in archivo.index.get_level_values(EMITIDO_EN):
            continue
        corrida = archivo.xs(emision, level=EMITIDO_EN)
        objetivo = corrida[
            (corrida.index >= pd.Timestamp(dia, tz="UTC"))
            & (corrida.index < pd.Timestamp(dia, tz="UTC") + pd.Timedelta(days=1))
        ]
        if len(objetivo) < 20:
            continue

        historia = (
            fuente.generacion(
                pd.Timestamp(inicio, tz="UTC") - pd.Timedelta(days=120),
                emision,
                emision,
            )[[POTENCIA_AC]]
            .resample("1h", label="left", closed="left")
            .mean()
            .dropna()
        )

        fila = {"real": verdad.reindex(objetivo.index)}
        for nombre, modelo in modelos.items():
            fila[nombre] = modelo.predecir(historia, objetivo[COLS_CLIMA], meta)
        bloques.append(pd.DataFrame(fila, index=objetivo.index))

    if not bloques:
        raise RuntimeError("ningún día utilizable: revise la hora de emisión y la ventana")
    return pd.concat(bloques).dropna(subset=["real"])
