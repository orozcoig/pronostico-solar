"""Regenera todo para la planta de referencia — `python -m banco.generar_todo`.

Un solo comando: planta sintética, archivo de pronóstico, conjunto operativo,
líneas base, modelo cuantílico, techo alcanzable y los artefactos que lee el
Colab.

    python -m banco.generar_todo              # 24 meses, ~6 min
    python -m banco.generar_todo --rapido     # 4 meses, ~1 min, para verificar
    python -m banco.generar_todo --sitio med-ref-560-dcac140

Es reproducible por semilla: dos corridas con los mismos parámetros dan los
mismos números. Si no los dan, algo cambió en las dependencias y hay que
mirarlo antes de publicar.
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import pandas as pd

from .artefactos import generar
from .backtest import correr
from .contrato import POTENCIA_AC
from .fuente import FuenteSintetica
from .lineas_base import LINEAS_BASE
from .mediciones import indice_desempeno_mensual
from .modelo import ArbolesGradiente, construir_conjunto, ordenar_cuantiles, particion_por_bloques
from .sitios import SITIOS
from .vara import comparar, mae_diario


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sitio", default="med-ref-500", choices=sorted(SITIOS))
    ap.add_argument("--rapido", action="store_true", help="4 meses en vez de 24")
    ap.add_argument("--salida", default="artefactos")
    ap.add_argument("--semilla", type=int, default=20261017)
    a = ap.parse_args()

    meta = SITIOS[a.sitio]
    meses = 4 if a.rapido else 24
    ini = dt.date(2023, 1, 1)
    fin = (pd.Timestamp(ini) + pd.DateOffset(months=meses)).date()
    d0 = ini + dt.timedelta(days=4)
    d1 = fin - dt.timedelta(days=7)
    t0 = time.time()

    def paso(msg):
        print(f"[{time.time() - t0:5.0f}s] {msg}", flush=True)

    paso(f"Planta {meta.nombre} · {meses} meses · semilla {a.semilla}")
    f = FuenteSintetica(meta, ini, fin, semilla=a.semilla)
    piso = 0.02 * meta.capacidad_ac_kw
    u, v = pd.Timestamp(ini, tz="UTC"), pd.Timestamp(fin, tz="UTC")

    paso("Conjunto operativo desde el pronóstico archivado…")
    conj = construir_conjunto(f, meta, d0, d1)
    tr, va, te = particion_por_bloques(conj)
    paso(f"  bloques: {len(set(tr.index.date))}/{len(set(va.index.date))}/"
         f"{len(set(te.index.date))} días (entrenamiento/validación/prueba)")

    paso("Líneas base con corte as-of…")
    pred_base = correr(f, meta, {lb.nombre: lb for lb in LINEAS_BASE}, d0, d1)

    paso("Modelo cuantílico q10/q50/q90…")
    mods = {q: ArbolesGradiente(max_iter=100, cuantil=q).entrenar(tr, va) for q in (.1, .5, .9)}
    Q = ordenar_cuantiles({q: m.predecir_conjunto(te) for q, m in mods.items()})
    pred = pd.DataFrame({"real": te["real"], **{f"q{int(q*100)}": Q[q] for q in Q}}).join(
        pred_base[[c for c in pred_base.columns if c != "real"]], how="inner")

    paso("Techo alcanzable (exige REENTRENAR con clima observado)…")
    cp = _conjunto_perfecto(f, meta, d0, d1)
    qp = ArbolesGradiente(max_iter=100, cuantil=.5).entrenar(
        cp.loc[cp.index.intersection(tr.index)], cp.loc[cp.index.intersection(va.index)])
    tp = cp.loc[cp.index.intersection(te.index)]
    techo = float((qp.predecir_conjunto(tp) - tp["real"])[tp["real"] > piso].abs().mean())

    vara = comparar(mae_diario(pred["q50"], pred["real"], piso),
                    mae_diario(pred["modelo_fisico"], pred["real"], piso), "q50", "fis").vara

    paso("Índice de desempeño y artefactos…")
    ide = indice_desempeno_mensual(f.verdad()[[POTENCIA_AC]], f.clima_observado(u, v), meta)
    carpeta = generar(a.salida, te, pred, ide, meta, techo, vara)

    mae = float((pred["q50"] - pred["real"])[pred["real"] > piso].abs().mean())
    base = float((pred["modelo_fisico"] - pred["real"])[pred["real"] > piso].abs().mean())
    print()
    print(f"  modelo q50 ............ {mae:6.2f} kW")
    print(f"  mejor línea base ...... {base:6.2f} kW  (mejora {base - mae:+.2f}, vara {vara:.2f})")
    print(f"  techo alcanzable ...... {techo:6.2f} kW")
    print(f"  error importado ....... {1 - techo / mae:6.1%} del total")
    print(f"\nArtefactos en {carpeta}/ — el Colab lee de ahí.")
    if a.rapido:
        print("\nOJO: corrida --rapido, 4 meses. Los números NO son los del README;")
        print("sirven para verificar que el pipeline corre, no para citar.")


def _conjunto_perfecto(f, meta, d0, d1):
    """Mismo conjunto pero con clima observado. NO es un pronóstico."""
    from .contrato import COLS_CLIMA, EMITIDO_EN
    from .modelo import construir_features

    verdad = (f.verdad()[POTENCIA_AC]
              .resample("1h", label="left", closed="left").mean().rename("real"))
    arch = f.clima_como_si_fuera_perfecto(
        pd.Timestamp(d0, tz="UTC"), pd.Timestamp(d1, tz="UTC") + pd.Timedelta(days=1))
    em = arch.index.get_level_values(EMITIDO_EN)
    bl = []
    for dia in pd.date_range(d0, d1, freq="D", inclusive="left"):
        e = pd.Timestamp(dia, tz="UTC") - pd.Timedelta(days=1) + pd.Timedelta(hours=12)
        if e not in em:
            continue
        c = arch.xs(e, level=EMITIDO_EN)
        o = c[(c.index >= pd.Timestamp(dia, tz="UTC"))
              & (c.index < pd.Timestamp(dia, tz="UTC") + pd.Timedelta(days=1))]
        if len(o) < 20:
            continue
        X = construir_features(o[COLS_CLIMA], meta)
        X["real"] = verdad.reindex(X.index)
        bl.append(X)
    return pd.concat(bl).dropna(subset=["real"])


if __name__ == "__main__":
    main()
