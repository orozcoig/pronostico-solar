"""`FuenteCSV`: el contrato leído desde archivos — Fase 3.6.

Existe para **demostrar** lo que la Fase 3.6 afirma: que pasar de planta
sintética a medición real es cambiar la fuente y no reescribir el código. Un
`Protocol` con un solo implementador no demuestra nada; la afirmación se
sostiene cuando el mismo agente de diagnóstico, sin tocar una línea, produce el
mismo veredicto leyendo de otro lado.

Los archivos se escriben como los escribe un historiador real, no como le
conviene al pipeline:

  * **Marcas de tiempo en hora LOCAL y sin zona horaria.** Es lo que sale de
    un portal de fabricante o de un export de SCADA. La conversión a UTC ocurre
    en el borde, al leer, usando la zona declarada en metadatos — que es
    exactamente lo que el invariante I1 del contrato exige y lo que nadie hace
    hasta que le explota una falla de cinco horas.
  * **Potencia en kW**, con la convención de etiqueta declarada aparte.
  * **Huecos como filas ausentes**, no como NaN. Es lo que hace un export real,
    y es lo que hizo fallar al detector de calidad hasta que se corrigió.

Nada de esto lo sabe el código que consume la fuente. Esa es la prueba.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .contrato import (
    COLS_CLIMA,
    EMITIDO_EN,
    HORIZONTE_H,
    INSTANTE,
    POTENCIA_AC,
    EtiquetaIntervalo,
    MetadatosSitio,
    PuntoMedicion,
    TipoMontaje,
    validar_clima,
    validar_generacion,
    validar_pronostico,
)

ARCHIVOS = {
    "sitio": "sitio.json",
    "generacion": "generacion.csv",
    "clima": "clima_observado.csv",
    "pronostico": "clima_pronosticado.csv",
    "eventos": "eventos.csv",
}


def _a_local(idx: pd.DatetimeIndex, zona: str) -> pd.Series:
    """UTC -> hora local sin zona horaria, como la escribe un historiador."""
    return idx.tz_convert(zona).tz_localize(None)


def _a_utc(s: pd.Series, zona: str) -> pd.DatetimeIndex:
    """Hora local sin zona -> UTC. La conversión ocurre en el BORDE (I1).

    La resolución se normaliza a segundos. `read_csv` devuelve microsegundos y
    el generador sintético trabaja en segundos; los valores coinciden pero el
    dtype no, y dos fuentes del mismo contrato que devuelven dtypes distintos
    rompen cualquier unión aguas abajo. Es la misma familia de problema que el
    desfase silencioso de mil veces: la resolución interna de pandas no es un
    detalle cosmético.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(s)).tz_localize(zona).tz_convert("UTC")
    return idx.as_unit("s")


def exportar_csv(fuente, carpeta: str | Path, desde=None, hasta=None) -> Path:
    """Vuelca una fuente al formato de archivos, en hora local y sin zona."""
    c = Path(carpeta)
    c.mkdir(parents=True, exist_ok=True)
    meta = fuente.metadatos_sitio()
    z = meta.zona_horaria

    d = asdict(meta)
    d["tipo_montaje"] = meta.tipo_montaje.value
    d["punto_medicion"] = meta.punto_medicion.value
    d["etiqueta_intervalo"] = meta.etiqueta_intervalo.value
    d["resolucion_nativa"] = str(meta.resolucion_nativa)
    d["rezago_publicacion"] = str(meta.rezago_publicacion)
    d["fecha_entrada_operacion"] = str(meta.fecha_entrada_operacion)
    d["campos_supuestos"] = list(meta.campos_supuestos)
    (c / ARCHIVOS["sitio"]).write_text(json.dumps(d, indent=2, ensure_ascii=False), "utf-8")

    a = desde or pd.Timestamp("1970-01-01", tz="UTC")
    b = hasta or pd.Timestamp("2100-01-01", tz="UTC")
    muy_tarde = pd.Timestamp("2099-01-01", tz="UTC")

    g = fuente.generacion(a, b, muy_tarde)
    g.assign(**{INSTANTE: _a_local(g.index, z)}).to_csv(
        c / ARCHIVOS["generacion"], index=False, columns=[INSTANTE, POTENCIA_AC]
    )

    cl = fuente.clima_observado(a, b)
    cl.assign(**{INSTANTE: _a_local(cl.index, z)}).to_csv(
        c / ARCHIVOS["clima"], index=False, columns=[INSTANTE] + COLS_CLIMA
    )

    pr = fuente.clima_pronosticado(a, b)
    if len(pr):
        pr = pr.reset_index()
        pr[EMITIDO_EN] = _a_local(pd.DatetimeIndex(pr[EMITIDO_EN]), z)
        pr[INSTANTE] = _a_local(pd.DatetimeIndex(pr[INSTANTE]), z)
        pr.to_csv(c / ARCHIVOS["pronostico"], index=False)

    fuente.eventos(a, b).to_csv(c / ARCHIVOS["eventos"], index=False)
    return c


class FuenteCSV:
    """Implementa `FuenteDeDatos` leyendo de la carpeta producida por `exportar_csv`."""

    def __init__(self, carpeta: str | Path) -> None:
        self._c = Path(carpeta)
        d = json.loads((self._c / ARCHIVOS["sitio"]).read_text("utf-8"))
        self._meta = MetadatosSitio(
            **{
                **d,
                "tipo_montaje": TipoMontaje(d["tipo_montaje"]),
                "punto_medicion": PuntoMedicion(d["punto_medicion"]),
                "etiqueta_intervalo": EtiquetaIntervalo(d["etiqueta_intervalo"]),
                "resolucion_nativa": pd.Timedelta(d["resolucion_nativa"]),
                "rezago_publicacion": pd.Timedelta(d["rezago_publicacion"]),
                "fecha_entrada_operacion": dt.date.fromisoformat(d["fecha_entrada_operacion"]),
                "campos_supuestos": tuple(d["campos_supuestos"]),
                "perfil_horizonte": d.get("perfil_horizonte"),
            }
        )
        z = self._meta.zona_horaria

        g = pd.read_csv(self._c / ARCHIVOS["generacion"])
        self._gen = g.set_index(_a_utc(g[INSTANTE], z))[[POTENCIA_AC]].sort_index()
        self._gen.index.name = INSTANTE

        cl = pd.read_csv(self._c / ARCHIVOS["clima"])
        self._clima = cl.set_index(_a_utc(cl[INSTANTE], z))[COLS_CLIMA].sort_index()
        self._clima.index.name = INSTANTE

        p = self._c / ARCHIVOS["pronostico"]
        if p.exists():
            pr = pd.read_csv(p)
            pr.index = pd.MultiIndex.from_arrays(
                [_a_utc(pr[EMITIDO_EN], z), _a_utc(pr[INSTANTE], z)],
                names=[EMITIDO_EN, INSTANTE],
            )
            self._pron = pr[COLS_CLIMA + [HORIZONTE_H]].sort_index()
        else:
            self._pron = None

        e = self._c / ARCHIVOS["eventos"]
        self._eventos = pd.read_csv(e) if e.exists() else pd.DataFrame()

        validar_generacion(self._gen, self._meta, "generación CSV")
        validar_clima(self._clima, "clima CSV")
        if self._pron is not None and len(self._pron):
            validar_pronostico(self._pron, "pronóstico CSV")

    # -- contrato -----------------------------------------------------------

    def metadatos_sitio(self) -> MetadatosSitio:
        return self._meta

    def generacion(self, inicio, fin, as_of) -> pd.DataFrame:
        corte = pd.Timestamp(as_of) - self._meta.rezago_publicacion
        v = self._gen.loc[pd.Timestamp(inicio) : pd.Timestamp(fin)]
        return v[v.index < corte].copy()

    def clima_observado(self, inicio, fin) -> pd.DataFrame:
        return self._clima.loc[pd.Timestamp(inicio) : pd.Timestamp(fin)].copy()

    def clima_pronosticado(self, valido_desde, valido_hasta, emitido_en=None) -> pd.DataFrame:
        if self._pron is None:
            raise FileNotFoundError("esta carpeta no incluye archivo de pronóstico")
        inst = self._pron.index.get_level_values(INSTANTE)
        v = self._pron[
            (inst >= pd.Timestamp(valido_desde)) & (inst < pd.Timestamp(valido_hasta))
        ]
        if emitido_en is None:
            return v.copy()
        return v.xs(pd.Timestamp(emitido_en), level=EMITIDO_EN, drop_level=False).copy()

    def eventos(self, inicio, fin) -> pd.DataFrame:
        return self._eventos.copy()

    def violaciones_de_contrato(self) -> list[str]:
        return []
