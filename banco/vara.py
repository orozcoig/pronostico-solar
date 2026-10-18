"""La vara — Fase 5.

Dos decisiones, y las dos cambian el resultado:

**Comparar por diferencias pareadas día a día, no por métricas globales.** Casi
toda la varianza del error es común a los dos modelos: un día de nube rota es
difícil para ambos. Al parear, esa parte se cancela y queda solo lo que los
distingue. Comparar MAE globales es mirar la diferencia a través del ruido que
ambos comparten.

**Error estándar por bootstrap de BLOQUES de 3 a 7 días.** Los días solares
están autocorrelacionados —los regímenes meteorológicos duran varios días—, así
que tratarlos como independientes subestima el error estándar y hace parecer
significativas diferencias que no lo son.

**Vara = 2 × ese error estándar, escrita ANTES de probar cualquier mejora.**
Si una mejora no la supera, se dice sin adornos.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Comparacion:
    a: str
    b: str
    dias: int
    mae_a: float
    mae_b: float
    diferencia: float          # mae_a - mae_b; negativo = a es mejor
    error_estandar: float
    vara: float
    bloque_min: int
    bloque_max: int

    @property
    def supera(self) -> bool:
        return abs(self.diferencia) > self.vara

    @property
    def mejor(self) -> str | None:
        if not self.supera:
            return None
        return self.a if self.diferencia < 0 else self.b

    def linea(self) -> str:
        veredicto = (
            f"{self.mejor} gana" if self.supera
            else "indistinguibles contra la vara"
        )
        return (
            f"{self.a} vs {self.b}: MAE {self.mae_a:.1f} vs {self.mae_b:.1f} kW | "
            f"dif {self.diferencia:+.2f} ± EE {self.error_estandar:.2f} | "
            f"vara {self.vara:.2f} -> {veredicto}"
        )


def mae_diario(prediccion: pd.Series, real: pd.Series, piso_kw: float) -> pd.Series:
    """MAE por día, restringido a horas con generación real apreciable.

    Incluir las horas de noche diluye el error con ceros que ningún modelo
    falla, y hace que todos los modelos se parezcan.
    """
    j = pd.DataFrame({"p": prediccion, "r": real}).dropna()
    j = j[j["r"] > piso_kw]
    if j.empty:
        return pd.Series(dtype=float)
    ae = (j["p"] - j["r"]).abs()
    return ae.groupby(ae.index.date).mean()


def _bootstrap_bloques(
    d: np.ndarray, bloque_min: int, bloque_max: int, n: int, rng: np.random.Generator
) -> np.ndarray:
    """Bootstrap de bloques de longitud variable sobre la serie de diferencias."""
    largo = len(d)
    medias = np.empty(n)
    for i in range(n):
        muestra = []
        while sum(len(x) for x in muestra) < largo:
            L = int(rng.integers(bloque_min, bloque_max + 1))
            ini = int(rng.integers(0, max(1, largo - L + 1)))
            muestra.append(d[ini : ini + L])
        medias[i] = np.concatenate(muestra)[:largo].mean()
    return medias


def comparar(
    mae_a: pd.Series,
    mae_b: pd.Series,
    nombre_a: str,
    nombre_b: str,
    bloque_min: int = 3,
    bloque_max: int = 7,
    n_boot: int = 2000,
    semilla: int = 5,
    dispersion_semillas: float = 0.0,
) -> Comparacion:
    """Compara dos modelos por diferencias pareadas día a día.

    `dispersion_semillas` es la desviación entre corridas del mismo modelo con
    semillas distintas; se suma EN CUADRATURA al error estándar. Si se comparan
    corridas sueltas de modelos con aleatoriedad —redes neuronales, por
    ejemplo— y se omite, la vara queda corta y la mitad de las "mejoras" son la
    semilla.
    """
    j = pd.DataFrame({"a": mae_a, "b": mae_b}).dropna().sort_index()
    if len(j) < bloque_max * 2:
        raise ValueError(
            f"{len(j)} días pareados: insuficiente para bloques de hasta {bloque_max}"
        )
    d = (j["a"] - j["b"]).to_numpy()
    rng = np.random.default_rng(semilla)
    ee = float(_bootstrap_bloques(d, bloque_min, bloque_max, n_boot, rng).std(ddof=1))
    ee = float(np.hypot(ee, dispersion_semillas))
    return Comparacion(
        a=nombre_a, b=nombre_b, dias=len(j),
        mae_a=float(j["a"].mean()), mae_b=float(j["b"].mean()),
        diferencia=float(d.mean()), error_estandar=ee, vara=2.0 * ee,
        bloque_min=bloque_min, bloque_max=bloque_max,
    )


def sensibilidad_al_bloque(
    mae_a: pd.Series, mae_b: pd.Series, nombre_a: str, nombre_b: str,
    bloques: tuple[tuple[int, int], ...] = ((1, 1), (3, 7), (7, 14)),
) -> pd.DataFrame:
    """Cuánto cambia la vara con la longitud de bloque.

    El bloque de 1 día es el bootstrap ingenuo —días independientes— y está
    aquí para mostrar cuánto subestima el error estándar, no como opción.
    """
    filas = []
    for lo, hi in bloques:
        c = comparar(mae_a, mae_b, nombre_a, nombre_b, bloque_min=lo, bloque_max=hi)
        filas.append({"bloque": f"{lo}-{hi} d", "diferencia": c.diferencia,
                      "error_estandar": c.error_estandar, "vara": c.vara,
                      "supera": c.supera})
    return pd.DataFrame(filas).set_index("bloque")
