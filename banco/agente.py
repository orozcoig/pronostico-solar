"""Agente de diagnóstico de referencia — línea base de la Fase 7.

No es el agente final: es la vara. Corre los detectores en el orden que las
dependencias imponen y emite un diagnóstico por hallazgo, con la medición que
lo dispara, la técnica que corresponde y las que NO corresponden.

**El orden no es preferencia, es dependencia.** Cada etapa puede contaminar a
las siguientes, y el banco lo demostró midiendo:

  1. ALINEACIÓN  — si las marcas de tiempo están corridas, todo lo demás miente.
  2. CALIDAD     — un valor congelado deprime la energía del día y se lee como
                   parada; hay que saber que es dato malo antes de culpar a
                   operación.
  3. OPERACIÓN   — una planta apagada tiene pico diario cero y dispara el
                   detector de limitación; las paradas van antes.
  4. EQUIPO      — recorte y capacidad: techos y niveles que el modelo hereda
                   de la placa.
  5. DEGRADACIÓN — suciedad, que solo se puede medir sobre lo que queda.
  6. GEOMETRÍA   — orientación y horizonte.
  7. METEOROLOGÍA— lo último: cuánto del error sobrante es importado.

Un agente que llegue al paso 7 sin haber hecho los seis anteriores va a
atribuirle al proveedor meteorológico errores que son suyos.

El agente DEBE poder concluir que no hay nada que corregir y detenerse. Esa
capacidad es el criterio 3.5 y vale más que encontrar diez cosas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .contrato import POTENCIA_AC, MetadatosSitio
from .mediciones import (
    asimetria_manana_tarde,
    dias_anomalos,
    desfase_mediodia_solar,
    dias_sospechosos,
    firma_recorte,
    indice_desempeno_mensual,
    rachas_pegadas,
    razon_por_elevacion,
    salto_de_nivel,
    techo_variable,
    tendencia_desempeno,
)

# Matriz de la Fase 7: qué aplicar y qué no, por diagnóstico.
TECNICAS = {
    "desfase_horario": (
        ["revisar convenciones horarias", "realinear contra el tránsito solar"],
        ["arquitectura", "más features", "ensamble"],
    ),
    "huecos_y_pegados": (
        ["control de calidad", "excluir los tramos antes de entrenar"],
        ["imputar y seguir", "entrenar sobre el tramo pegado"],
    ),
    "paradas_mantenimiento": (
        ["investigar paradas", "marcar o excluir esos días"],
        ["cualquier cambio al modelo"],
    ),
    "limitacion_operador": (
        ["modelar lo que va a entregar, no lo que podría producir", "dos modelos"],
        ["más features meteorológicas", "más capacidad"],
    ),
    "recorte_inversor": (
        ["modelo consciente de capacidad AC/DC", "pérdida que respete el techo"],
        ["más features meteorológicas"],
    ),
    "ampliacion_capacidad": (
        ["normalizar por capacidad", "ventana móvil", "reentrenamiento"],
        ["acumular datos antiguos sin normalizar"],
    ),
    "deriva_suciedad": (
        ["días desde el último lavado", "ventana móvil"],
        ["reentrenar sin separar la causa"],
    ),
    "orientacion_declarada": (
        ["corregir la geometría en metadatos", "recalcular el plano del arreglo"],
        ["arquitectura"],
    ),
    "sombreado_horizonte": (
        ["perfil de horizonte", "ángulo de incidencia"],
        ["arquitectura"],
    ),
    "sesgo_meteorologico": (
        ["post-proceso del NWP", "mezcla de fuentes", "ensamble", "salida probabilística"],
        ["seguir optimizando el modelo PV", "más features de planta"],
    ),
}


@dataclass
class Hallazgo:
    falla: str
    detector: str
    etapa: str
    evidencia: dict
    tecnicas_si: list = field(default_factory=list)
    tecnicas_no: list = field(default_factory=list)

    @classmethod
    def de(cls, falla: str, detector: str, etapa: str, evidencia: dict) -> "Hallazgo":
        si, no = TECNICAS[falla]
        return cls(falla, detector, etapa, evidencia, list(si), list(no))


def _etapa_operacion_y_equipo(
    gen: pd.DataFrame, clima: pd.DataFrame, meta: MetadatosSitio
) -> list[Hallazgo]:
    """Etapas 4 y 5, aplicables a UN régimen de capacidad.

    Van juntas y por régimen porque ambas leen niveles de potencia, y un cambio
    de capacidad a mitad de serie los corre a los dos: el pico diario cambia de
    nivel (se lee como limitación del operador) y el percentil alto se concentra
    en el régimen nuevo (se lee como recorte). Ninguna de las dos fallas estaba
    inyectada en esos casos.
    """
    out = []
    a = dias_anomalos(gen, clima, meta)
    if a["detectado"]:
        out.append(Hallazgo.de("paradas_mantenimiento", "dias_anomalos", "operacion", a))
    t = techo_variable(gen, clima, meta)
    if t["detectado"]:
        out.append(Hallazgo.de("limitacion_operador", "techo_variable", "operacion", t))
    c = firma_recorte(gen, meta)
    if c["detectado"]:
        out.append(Hallazgo.de("recorte_inversor", "firma_recorte", "equipo", c))
    return out


def diagnosticar(
    generacion: pd.DataFrame,
    clima: pd.DataFrame,
    meta: MetadatosSitio,
    techo_alcanzable: dict | None = None,
    violaciones: list[str] | None = None,
) -> list[Hallazgo]:
    """Recorre las etapas en orden y devuelve los hallazgos.

    Lista vacía = no hay nada que corregir. Es una respuesta válida y, sobre el
    control negativo, es la única correcta.

    Las dos primeras etapas y la tercera son NORMALIZACIONES, no diagnósticos
    finales: corrigen el dato para que lo que sigue mida lo que dice medir.
    """
    hallazgos: list[Hallazgo] = []
    # La calidad se mide sobre la serie COMO LLEGÓ. La etapa de alineación
    # descarta los días que no logró corregir, y si la calidad mirara el
    # resultado, el agente acusaría de huecos los días que él mismo quitó.
    original = generacion

    # 1. ALINEACIÓN TEMPORAL
    d = desfase_mediodia_solar(generacion, meta)
    if len(d) > 30:
        mediana = float(d.desfase_min.median())
        suave = d.desfase_min.rolling(15, center=True, min_periods=8).median()
        dif = suave.diff().abs()
        # Sin los bordes: al llenarse la ventana centrada el valor salta
        # artificialmente y el punto de cambio se iba al primer día, con lo que
        # un tramo quedaba vacío y la realineación por tramos degeneraba en la
        # global — que es justo lo que se quería evitar.
        borde = 20
        interior = dif.iloc[borde:-borde] if len(dif) > 3 * borde else dif
        salto = float(interior.max() or 0.0)
        if abs(mediana) > 20 or salto > 20:
            hallazgos.append(
                Hallazgo.de(
                    "desfase_horario", "desfase_mediodia_solar", "alineacion",
                    {"desfase_mediano_min": mediana, "mayor_salto_min": salto},
                )
            )
            cortes = (
                [None, interior.index[int(interior.to_numpy().argmax())], None]
                if salto > 20 else [None, None]
            )
            fechas = pd.Index(generacion.index.date)
            minutos = np.zeros(len(generacion))
            for a_, b_ in zip(cortes[:-1], cortes[1:]):
                sub = d.desfase_min
                if a_ is not None:
                    sub = sub[sub.index >= a_]
                if b_ is not None:
                    sub = sub[sub.index < b_]
                if not len(sub):
                    continue
                m = np.ones(len(generacion), dtype=bool)
                if a_ is not None:
                    m &= fechas >= a_
                if b_ is not None:
                    m &= fechas < b_
                minutos[m] = -round(float(sub.median()) / 15.0) * 15.0
            if np.any(minutos):
                generacion = generacion.set_index(
                    generacion.index + pd.to_timedelta(minutos, unit="m")
                ).sort_index()
                generacion = generacion[~generacion.index.duplicated()]
                generacion = generacion.reindex(clima.index.intersection(generacion.index))
                # VERIFICAR LA PROPIA CORRECCIÓN. El punto de cambio se localiza
                # con resolución de días, así que los días entre el cambio real
                # y el detectado quedan sin alinear. Veinte días corridos una
                # hora bastaban para que la asimetría mañana/tarde acusara una
                # orientación equivocada que no existía. Se vuelve a medir y se
                # descartan los días que siguen desalineados.
                d2 = desfase_mediodia_solar(generacion, meta)
                malos = set(d2.index[d2.desfase_min.abs() > 20])
                if malos:
                    generacion = generacion[~pd.Index(generacion.index.date).isin(malos)]

    # 2. CALIDAD DE DATOS
    r = rachas_pegadas(original, meta)
    if r["detectado"] and r.get("diagnostico") != "consigna del operador o recorte":
        hallazgos.append(Hallazgo.de("huecos_y_pegados", "rachas_pegadas", "calidad", r))
    sucios = dias_sospechosos(original, meta)
    if sucios:
        generacion = generacion[~pd.Index(generacion.index.date).isin(sucios)]
        clima = clima.loc[generacion.index.min() : generacion.index.max()]
        clima = clima[~pd.Index(clima.index.date).isin(sucios)]

    # 3. NIVEL DE CAPACIDAD — normalización, no diagnóstico de equipo.
    # Va aquí porque un cambio de nivel contamina TODO lo que mide potencia.
    ide = indice_desempeno_mensual(generacion, clima, meta)
    n = salto_de_nivel(ide)
    sobre_placa = float((generacion[POTENCIA_AC] > 1.05 * meta.capacidad_ac_kw).mean())
    if sobre_placa > 0.001 and not n["detectado"]:
        n = dict(n, detectado=True, fraccion_sobre_placa=sobre_placa)
    if n["detectado"]:
        hallazgos.append(Hallazgo.de("ampliacion_capacidad", "salto_de_nivel", "capacidad", n))

    regimenes = [generacion]
    if n["detectado"] and n.get("mes_del_salto"):
        # BANDA DE GUARDA: el salto se localiza con resolución MENSUAL, pero la
        # ampliación ocurre un día cualquiera del mes. Sin descartar ese mes, el
        # régimen nuevo arrastra los días viejos y su pico diario tiene dos
        # niveles: se diagnosticaba limitación del operador que nadie inyectó.
        corte = pd.Period(n["mes_del_salto"]).to_timestamp().tz_localize("UTC")
        fin_guarda = (pd.Period(n["mes_del_salto"]) + 1).to_timestamp().tz_localize("UTC")
        regimenes = [
            g for g in (generacion.loc[:corte], generacion.loc[fin_guarda:]) if len(g) > 5000
        ]

    # 4 y 5. OPERACIÓN Y EQUIPO, por régimen
    vistos = set()
    for parte in regimenes:
        sub_clima = clima.loc[parte.index.min() : parte.index.max()]
        for h in _etapa_operacion_y_equipo(parte, sub_clima, meta):
            if h.falla not in vistos:
                vistos.add(h.falla)
                hallazgos.append(h)

    # 6. GEOMETRÍA
    g = asimetria_manana_tarde(generacion, clima, meta)
    if g["detectado"]:
        hallazgos.append(
            Hallazgo.de("orientacion_declarada", "asimetria_manana_tarde", "geometria", g)
        )
    e = razon_por_elevacion(generacion, clima, meta)
    if e["detectado"]:
        hallazgos.append(Hallazgo.de("sombreado_horizonte", "razon_por_elevacion", "geometria", e))

    # 7. DEGRADACIÓN — después de la geometría, y solo si la geometría está
    # limpia. El índice de desempeño se construye contra una potencia esperada
    # que depende de la inclinación y el azimut DECLARADOS; si están mal, el
    # índice oscila con la estación y el ajuste lo lee como ensuciamiento. Es
    # el mismo principio que la alineación: no se interpretan tendencias sobre
    # una referencia que se sabe equivocada.
    hay_geometria = any(h.etapa == "geometria" for h in hallazgos)
    s = tendencia_desempeno(ide)
    if s["detectado"] and s.get("separable_de_estacionalidad") and not hay_geometria:
        hallazgos.append(Hallazgo.de("deriva_suciedad", "tendencia_desempeno", "degradacion", s))

    # 8. METEOROLOGÍA — lo último, y solo con el techo alcanzable medido
    if techo_alcanzable is not None and techo_alcanzable.get("sesgo_importado"):
        hallazgos.append(
            Hallazgo.de("sesgo_meteorologico", "techo_alcanzable", "meteorologia", techo_alcanzable)
        )

    return hallazgos


def resumen(hallazgos: list[Hallazgo]) -> str:
    if not hallazgos:
        return "Sin hallazgos: no hay nada que corregir en los datos. Detenerse."
    lineas = []
    for h in hallazgos:
        lineas.append(
            f"[{h.etapa}] {h.falla} — detectado por {h.detector}\n"
            f"    aplicar: {', '.join(h.tecnicas_si)}\n"
            f"    NO aplicar: {', '.join(h.tecnicas_no)}"
        )
    return "\n".join(lineas)
