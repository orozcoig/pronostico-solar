"""Artefactos precomputados y figuras — insumo del Colab y de la propuesta.

El cuaderno que abre el cliente **no entrena nada**. Si espera cinco minutos la
primera vez, no lo vuelve a abrir. Este módulo deja todo resuelto en parquet y
PNG versionados, y el Colab solo lee.

Produce, en `artefactos/`:

    conjunto.parquet     features del pronóstico archivado + verdad horaria
    predicciones.parquet líneas base, modelo puntual y cuantiles, con la verdad
    resumen.json         los números que van en la lectura de negocio
    fig_pronostico.png   pronóstico contra real, con banda 10-90
    fig_residuo.png      residuo por hora y por banda de elevación solar
    fig_desempeno.png    índice de desempeño mensual

Los parquet llevan el conjunto y las predicciones, no la serie de 5 minutos:
esa pesa cientos de MB y el Colab no la necesita. Si alguien la necesita,
regenera desde la fuente, que es reproducible por semilla.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

# NO se fuerza el backend "Agg". Matplotlib ya lo elige solo cuando no hay
# pantalla —en un servidor o en integración continua—, y forzarlo rompe el uso
# interactivo: en Colab las figuras se generaban correctamente pero no se veían
# nunca, porque "Agg" no dibuja en pantalla y abajo se cerraba la figura.
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .contrato import POTENCIA_AC  # noqa: E402

PALETA = {"real": "#8A6D1F", "relleno": "#E9C46A", "modelo": "#2A6F97",
          "fisico": "#588B8B", "clima": "#6D597A", "pers": "#C8553D",
          "banda": "#2A6F97"}


def _fig(ax_titulo: str, figsize=(10, 4.2)):
    fig, ax = plt.subplots(figsize=figsize, dpi=120)
    ax.set_title(ax_titulo)
    ax.spines[["top", "right"]].set_visible(False)
    return fig, ax


def figura_pronostico(pred: pd.DataFrame, meta, dias: int = 10, archivo=None):
    """Pronóstico contra real con banda 10-90. La figura que mira el cliente.

    Se muestran días consecutivos, no los mejores: elegir los días bonitos es
    la forma más fácil de mentir con una gráfica correcta.
    """
    d = pred.tail(dias * 24)
    fig, ax = _fig(f"Generación pronosticada vs. real — últimos {dias} días")
    if {"q10", "q90"} <= set(d.columns):
        ax.fill_between(d.index, d["q10"], d["q90"], color=PALETA["banda"], alpha=.18,
                        label="banda 10–90 %")
    ax.plot(d.index, d["real"], color=PALETA["real"], lw=1.8, label="Real (medido)")
    if "q50" in d:
        ax.plot(d.index, d["q50"], color=PALETA["modelo"], lw=1.4, label="Pronóstico (mediana)")
    if "modelo_fisico" in d:
        ax.plot(d.index, d["modelo_fisico"], color=PALETA["fisico"], lw=1.0, ls="--",
                label="Línea base física")
    ax.axhline(meta.capacidad_ac_kw, color="#999", lw=.8, ls=":")
    ax.text(d.index[0], meta.capacidad_ac_kw * 1.01, "capacidad AC", color="#777", fontsize=7)
    ax.set(xlabel="", ylabel="Potencia (kW)")
    ax.legend(frameon=False, fontsize=8, ncol=4)
    fig.autofmt_xdate()
    fig.tight_layout()
    # Cerrar SOLO si se guardó a disco. Si no, se devuelve la figura para que
    # el cuaderno la muestre: cerrarla siempre la hacía desaparecer en Colab.
    if archivo:
        fig.savefig(archivo)
        plt.close(fig)
        return None
    return fig


def figura_residuo(pred: pd.DataFrame, conjunto: pd.DataFrame, meta, archivo=None):
    """Residuo por hora del día y por banda de elevación solar.

    Son las dos vistas que disparan filas distintas de la matriz: concentración
    por hora apunta a geometría o alineación; concentración a sol bajo apunta a
    horizonte o transposición. Verlas juntas evita confundirlas.
    """
    piso = 0.02 * meta.capacidad_ac_kw
    col = "q50" if "q50" in pred else "modelo_fisico"
    j = pd.DataFrame({"e": pred[col] - pred["real"], "real": pred["real"]}).join(
        conjunto[["elevacion_sol"]], how="inner").dropna()
    j = j[j["real"] > piso]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8), dpi=120)
    por_hora = j.groupby(j.index.hour)["e"]
    a1.bar(por_hora.mean().index, por_hora.apply(lambda s: s.abs().mean()),
           color=PALETA["modelo"], alpha=.75, label="MAE")
    a1.plot(por_hora.mean().index, por_hora.mean(), color=PALETA["pers"], lw=1.6,
            marker="o", ms=3, label="sesgo")
    a1.axhline(0, color="#999", lw=.8)
    a1.set(title="Residuo por hora (UTC)", xlabel="hora", ylabel="kW")
    a1.legend(frameon=False, fontsize=8)

    bandas = pd.cut(j["elevacion_sol"], [0, 10, 20, 35, 90])
    g = j.groupby(bandas, observed=True)["e"]
    etq = [f"{int(i.left)}–{int(i.right)}°" for i in g.mean().index]
    a2.bar(etq, g.apply(lambda s: s.abs().mean()), color=PALETA["fisico"], alpha=.8, label="MAE")
    a2.plot(etq, g.mean(), color=PALETA["pers"], lw=1.6, marker="o", ms=3, label="sesgo")
    a2.axhline(0, color="#999", lw=.8)
    a2.set(title="Residuo por elevación solar", xlabel="elevación", ylabel="kW")
    a2.legend(frameon=False, fontsize=8)
    for a in (a1, a2):
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    # Cerrar SOLO si se guardó a disco. Si no, se devuelve la figura para que
    # el cuaderno la muestre: cerrarla siempre la hacía desaparecer en Colab.
    if archivo:
        fig.savefig(archivo)
        plt.close(fig)
        return None
    return fig


def figura_desempeno(ide: pd.Series, archivo=None):
    """Índice de desempeño mensual: la vista que delata deriva y saltos."""
    fig, ax = _fig("Índice de desempeño mensual (medido / esperado por irradiancia)",
                   figsize=(10, 3.6))
    x = [p.to_timestamp() for p in ide.index]
    ax.plot(x, ide.to_numpy(), color=PALETA["fisico"], lw=1.8, marker="o", ms=4)
    ax.axhline(float(ide.median()), color="#999", lw=.8, ls=":")
    ax.set(xlabel="", ylabel="razón")
    ax.set_ylim(min(0.9, ide.min() * .98), max(1.05, ide.max() * 1.02))
    fig.autofmt_xdate()
    fig.tight_layout()
    # Cerrar SOLO si se guardó a disco. Si no, se devuelve la figura para que
    # el cuaderno la muestre: cerrarla siempre la hacía desaparecer en Colab.
    if archivo:
        fig.savefig(archivo)
        plt.close(fig)
        return None
    return fig


def resumen_negocio(pred: pd.DataFrame, meta, mae_techo: float, vara: float,
                    mejor_base: str = "modelo_fisico") -> dict:
    """Los números de la lectura de negocio, calculados una vez.

    Se guardan con su contexto —qué fracción del error NO es comprable, cuál es
    la vara— porque un MAE suelto en una diapositiva se lee como promesa.
    """
    piso = 0.02 * meta.capacidad_ac_kw
    sol = pred["real"] > piso
    col = "q50" if "q50" in pred else mejor_base
    mae = float((pred[col] - pred["real"])[sol].abs().mean())
    med = float(pred["real"][sol].mean())
    base = float((pred[mejor_base] - pred["real"])[sol].abs().mean())
    d = {
        "dias_evaluados": int(pred.index.normalize().nunique()),
        "generacion_media_diurna_kw": round(med, 1),
        "mae_modelo_kw": round(mae, 2),
        "nmae_modelo": round(mae / med, 4),
        "mae_mejor_linea_base_kw": round(base, 2),
        "mejora_sobre_linea_base_kw": round(base - mae, 2),
        "vara_kw": round(vara, 2),
        "supera_la_vara": bool(base - mae > vara),
        "mae_techo_alcanzable_kw": round(mae_techo, 2),
        "fraccion_error_importada_del_meteorologico": round(1 - mae_techo / mae, 3),
    }
    if {"q10", "q90"} <= set(pred.columns):
        dd = pred[sol]
        d["cobertura_banda_10_90"] = round(
            float(((dd["real"] >= dd["q10"]) & (dd["real"] <= dd["q90"])).mean()), 3)
        d["ancho_mediano_banda_kw"] = round(float((dd["q90"] - dd["q10"]).median()), 1)
        d["ancho_banda_sobre_placa"] = round(
            float((dd["q90"] - dd["q10"]).median()) / meta.capacidad_ac_kw, 3)
    d["advertencia"] = (
        "Cifras sobre planta SINTÉTICA de referencia. No transferibles a un sitio real. "
        "La métrica y el horizonte dependen de la Fase 1: ver DEPENDENCIAS_FASE1.md."
    )
    return d


def generar(carpeta: str | Path, conjunto: pd.DataFrame, pred: pd.DataFrame,
            ide: pd.Series, meta, mae_techo: float, vara: float) -> Path:
    c = Path(carpeta)
    c.mkdir(parents=True, exist_ok=True)
    conjunto.to_parquet(c / "conjunto.parquet")
    pred.to_parquet(c / "predicciones.parquet")
    res = resumen_negocio(pred, meta, mae_techo, vara)
    (c / "resumen.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), "utf-8")
    figura_pronostico(pred, meta, archivo=c / "fig_pronostico.png")
    figura_residuo(pred, conjunto, meta, archivo=c / "fig_residuo.png")
    figura_desempeno(ide, archivo=c / "fig_desempeno.png")
    return c
