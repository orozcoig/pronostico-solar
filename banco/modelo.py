"""Primer modelo — Fase 6.

No busca el mejor modelo: busca uno **correcto y comparable**. Es el que la
Fase 7 va a diagnosticar y contra el que se mide la regla de entrada de la red.

Tres cosas que no son negociables aquí:

  * **El conjunto se construye con el pronóstico ARCHIVADO**, el que existía en
    la hora de emisión, no con clima observado ni con una corrida posterior.
    Entrenar con clima casi perfecto y prometer desempeño operativo es la fuga
    más cara del proyecto.

  * **Partición temporal por bloques contiguos, nunca aleatoria.** Partir días
    al azar filtra información entre entrenamiento y prueba: el día siguiente
    comparte régimen meteorológico con el anterior, así que un día de prueba
    rodeado de días de entrenamiento es casi un día visto. Además va una
    separación entre bloques, para que la autocorrelación no cruce el borde.

  * **Features mínimas.** Irradiancia pronosticada transpuesta al plano del
    arreglo, ángulo solar, índice de cielo despejado, temperatura, hora y día
    del año. Cualquier feature adicional entra solo si supera la vara.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pvlib.location import Location

from .clima import ParametrosClima
from .contrato import (
    COLS_CLIMA,
    EMITIDO_EN,
    GHI,
    POTENCIA_AC,
    TEMP_AIRE,
    MetadatosSitio,
)
from .planta import ParametrosPlanta, simular_generacion

FEATURES = [
    "poa_wm2",        # irradiancia pronosticada en el plano del arreglo
    "elevacion_sol",  # ángulo solar
    "azimut_sol",
    "kc",             # índice de cielo despejado pronosticado
    "temp_aire_c",
    "hora_sin", "hora_cos",
    "doy_sin", "doy_cos",
]


def construir_features(
    clima_pron: pd.DataFrame, meta: MetadatosSitio, pc: ParametrosClima | None = None
) -> pd.DataFrame:
    """Features mínimas a partir de un pronóstico horario.

    La transposición al plano del arreglo se hace con la misma cadena física que
    usa el banco: el modelo tabular NO tiene que re-aprender geometría solar a
    partir de hora y día del año, que es lo que haría si se le pasara GHI cruda.
    """
    pc = pc or ParametrosClima()
    idx = clima_pron.index
    centro = idx + pd.Timedelta(minutes=30)

    c = clima_pron.copy()
    c.index = centro
    det = simular_generacion(meta, c, ParametrosPlanta(suciedad_base=0.0), detalle=True)

    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    pos = sitio.get_solarposition(centro)
    doy = centro.dayofyear.to_numpy()
    linke = pc.linke_media + pc.linke_amplitud * np.cos(
        2 * np.pi * (doy - pc.linke_doy_max) / 365.25
    )
    cs = sitio.get_clearsky(centro, model="ineichen",
                            linke_turbidity=pd.Series(linke, index=centro))
    with np.errstate(invalid="ignore", divide="ignore"):
        kc = np.where(cs["ghi"].to_numpy() > 1.0,
                      clima_pron[GHI].to_numpy() / cs["ghi"].to_numpy(), 0.0)

    local = centro.tz_convert(meta.zona_horaria)
    h = local.hour.to_numpy() + local.minute.to_numpy() / 60.0
    return pd.DataFrame(
        {
            "poa_wm2": det["poa_efectiva_wm2"].to_numpy(),
            "elevacion_sol": pos["elevation"].to_numpy(),
            "azimut_sol": pos["azimuth"].to_numpy(),
            "kc": np.clip(np.nan_to_num(kc), 0.0, 1.3),
            "temp_aire_c": clima_pron[TEMP_AIRE].to_numpy(),
            "hora_sin": np.sin(2 * np.pi * h / 24.0),
            "hora_cos": np.cos(2 * np.pi * h / 24.0),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
        },
        index=idx,
    )


def construir_conjunto(
    fuente, meta: MetadatosSitio, inicio: dt.date, fin: dt.date,
    hora_emision_utc: int = 12,
) -> pd.DataFrame:
    """Conjunto operativo: features del pronóstico archivado + verdad horaria.

    Un día objetivo entra una sola vez, con la corrida emitida el día anterior
    a la hora de emisión. Ese es el conjunto de información que va a existir en
    operación, y por lo tanto el único con el que es honesto entrenar.
    """
    verdad = (fuente.verdad()[POTENCIA_AC]
              .resample("1h", label="left", closed="left").mean().rename("real"))
    archivo = fuente.clima_pronosticado(
        pd.Timestamp(inicio, tz="UTC"),
        pd.Timestamp(fin, tz="UTC") + pd.Timedelta(days=1),
    )
    emisiones = archivo.index.get_level_values(EMITIDO_EN)
    bloques = []
    for dia in pd.date_range(inicio, fin, freq="D", inclusive="left"):
        emision = pd.Timestamp(dia, tz="UTC") - pd.Timedelta(days=1) + pd.Timedelta(
            hours=hora_emision_utc
        )
        if emision not in emisiones:
            continue
        corrida = archivo.xs(emision, level=EMITIDO_EN)
        obj = corrida[(corrida.index >= pd.Timestamp(dia, tz="UTC"))
                      & (corrida.index < pd.Timestamp(dia, tz="UTC") + pd.Timedelta(days=1))]
        if len(obj) < 20:
            continue
        X = construir_features(obj[COLS_CLIMA], meta)
        X["real"] = verdad.reindex(X.index)
        X["emitido_en"] = emision
        bloques.append(X)
    return pd.concat(bloques).dropna(subset=["real"])


def particion_por_bloques(
    conjunto: pd.DataFrame, fracciones=(0.6, 0.2, 0.2), separacion_dias: int = 7
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Tres bloques CONTIGUOS en el tiempo, con separación entre ellos.

    La separación descarta los días del borde. Sin ella, el último día de
    entrenamiento y el primero de validación comparten régimen meteorológico, y
    la validación queda optimista por contigüidad aunque la partición sea
    temporal.
    """
    dias = np.array(sorted(set(conjunto.index.date)))
    n = len(dias)
    c1 = int(n * fracciones[0])
    c2 = int(n * (fracciones[0] + fracciones[1]))
    sep = separacion_dias
    tramos = [
        dias[: c1 - sep],
        dias[c1 : c2 - sep],
        dias[c2:],
    ]
    fechas = pd.Index(conjunto.index.date)
    return tuple(conjunto[fechas.isin(set(t))] for t in tramos)


@dataclass
class ArbolesGradiente:
    """Modelo inicial deliberadamente simple: rápido y difícil de equivocar.

    Fija la referencia contra la cual se mide todo lo demás, incluida la red.
    """

    cuantil: float | None = None     # None = media; un valor = pérdida pinball
    semilla: int = 0
    max_iter: int = 300
    nombre: str = field(default="arboles_gradiente", init=False)
    _modelo: object = field(default=None, init=False, repr=False)

    def entrenar(self, entrenamiento: pd.DataFrame, validacion: pd.DataFrame | None = None):
        from sklearn.ensemble import HistGradientBoostingRegressor

        # early_stopping=False A PROPÓSITO. La parada temprana de sklearn
        # separa su validación AL AZAR dentro del entrenamiento, que es
        # exactamente la partición aleatoria que esta fase prohíbe: en serie
        # temporal filtra información entre ajuste y validación y hace parecer
        # buena una configuración que no lo es. El número de iteraciones se
        # elige sobre el bloque de validación TEMPORAL, fuera de la librería.
        kw = dict(max_iter=self.max_iter, learning_rate=0.06, max_depth=6,
                  l2_regularization=1.0, random_state=self.semilla,
                  early_stopping=False)
        if self.cuantil is not None:
            kw.update(loss="quantile", quantile=self.cuantil)
        self._modelo = HistGradientBoostingRegressor(**kw)
        self._modelo.fit(entrenamiento[FEATURES], entrenamiento["real"])
        if validacion is not None and len(validacion):
            # Horas de sol en AMBOS, si no la razón validación/entrenamiento no
            # significa nada: la validación con noches incluidas sale más baja
            # por los ceros que nadie falla, y la fila de sobreajuste nunca
            # dispara aunque el sobreajuste sea evidente.
            def _mae(c):
                piso = 0.02 * c["real"].max()
                m = c["real"] > piso
                return float((self.predecir_conjunto(c)[m] - c["real"][m]).abs().mean())
            self.mae_validacion = _mae(validacion)
            self.mae_entrenamiento = _mae(entrenamiento)
        if self.cuantil is not None:
            self.nombre = f"arboles_q{int(self.cuantil * 100)}"
        return self

    def predecir(self, historia, clima_pron, meta) -> pd.Series:
        """Misma interfaz que las líneas base, para que el arnés no distinga."""
        X = construir_features(clima_pron, meta)
        y = self._modelo.predict(X[FEATURES])
        return pd.Series(np.clip(y, 0.0, meta.capacidad_ac_kw), index=X.index)

    def predecir_conjunto(self, conjunto: pd.DataFrame) -> pd.Series:
        y = self._modelo.predict(conjunto[FEATURES])
        return pd.Series(np.clip(y, 0.0, None), index=conjunto.index)


def ordenar_cuantiles(predicciones: dict[float, pd.Series]) -> dict[float, pd.Series]:
    """Post-proceso monótono: impone q10 <= q50 <= q90 hora por hora.

    Cuantiles entrenados por separado pueden cruzarse —cada uno optimiza su
    propia pérdida sin saber de los otros—, y un intervalo con el extremo
    inferior por encima del superior no es interpretable. Reordenar los valores
    de cada instante es la corrección mínima: **no cambia la pérdida pinball de
    ningún cuantil en promedio** (reordenar solo puede bajarla), y deja el
    intervalo bien formado.

    La alternativa de fondo es un modelo que emita los tres a la vez con una
    pérdida conjunta, que es una de las dos razones legítimas para pasar a una
    red neuronal.
    """
    qs = sorted(predicciones)
    M = np.sort(np.column_stack([predicciones[q].to_numpy() for q in qs]), axis=1)
    idx = predicciones[qs[0]].index
    return {q: pd.Series(M[:, i], index=idx) for i, q in enumerate(qs)}
