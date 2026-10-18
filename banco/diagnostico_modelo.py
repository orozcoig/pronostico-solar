"""Agente de diagnóstico del MODELO — la matriz de la Fase 7.

El agente de `agente.py` diagnostica los DATOS: desfases, paradas, suciedad.
Este diagnostica el MODELO ya entrenado, a partir de sus residuos.

Para cada fila el agente nombra la medición y el umbral que disparan el
diagnóstico, justifica la técnica por su mecanismo, dice qué esperaría ver si
el diagnóstico es correcto y qué si no, y enumera lo que NO aplica. Un
diagnóstico sin predicción falsable es una opinión.

El primer experimento es obligatorio y va siempre primero: alimentar el modelo
con clima observado para medir el techo alcanzable. Separa el error importado
del proveedor meteorológico del error propio del modelo, y es la única forma
honesta de decirle a un cliente cuánta mejora hay realmente en venta. Hacerlo
mal —cambiando el insumo sin reentrenar— sobreestima el error propio, porque el
modelo entrenado con pronóstico aprendió a corregir su sesgo y sigue
aplicándolo sobre un clima que ya no lo tiene.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Diagnostico:
    sintoma: str
    medicion: str
    valor: str
    umbral: str
    diagnostico: str
    aplicar: list
    no_aplicar: list
    si_acierto: str = ""
    si_error: str = ""
    orden: int = 99

    def texto(self) -> str:
        return (
            f"[{self.diagnostico}]\n"
            f"    síntoma   : {self.sintoma}\n"
            f"    medición  : {self.medicion} = {self.valor}  (umbral {self.umbral})\n"
            f"    aplicar   : {', '.join(self.aplicar)}\n"
            f"    NO aplicar: {', '.join(self.no_aplicar)}\n"
            + (f"    si acierta: {self.si_acierto}\n" if self.si_acierto else "")
            + (f"    si falla  : {self.si_error}\n" if self.si_error else "")
        )


def diagnosticar_modelo(
    real: pd.Series,
    prediccion: pd.Series,
    conjunto: pd.DataFrame,
    meta,
    mae_entrenamiento: float | None = None,
    mae_validacion: float | None = None,
    mae_con_observado: float | None = None,
) -> list[Diagnostico]:
    """Recorre la matriz sobre los residuos de un modelo ya entrenado."""
    piso = 0.02 * meta.capacidad_ac_kw
    j = pd.DataFrame({"real": real, "pred": prediccion}).join(
        conjunto[["kc", "elevacion_sol", "poa_wm2"]], how="inner"
    ).dropna()
    j = j[j["real"] > piso]
    e = j["pred"] - j["real"]
    mae = float(e.abs().mean())
    sesgo = float(e.mean())
    out: list[Diagnostico] = []

    # --- 1. Primer experimento: ¿de quién es el error?
    if mae_con_observado is not None:
        frac = 1.0 - mae_con_observado / max(mae, 1e-9)
        if frac > 0.5:
            out.append(Diagnostico(
                sintoma="error con clima observado muy por debajo del error con pronóstico",
                medicion="1 - MAE(observado)/MAE(pronóstico)",
                valor=f"{frac:.0%} ({mae_con_observado:.1f} vs {mae:.1f} kW)",
                umbral="> 50 %", diagnostico="error IMPORTADO del meteorológico",
                aplicar=["mezcla de fuentes", "post-proceso del NWP",
                         "ensamble meteorológico", "salida probabilística"],
                no_aplicar=["seguir optimizando el modelo PV", "más features de planta"],
                si_acierto="cambiar de proveedor o post-procesar mueve el error; "
                           "tocar el modelo PV casi no lo mueve",
                si_error="post-procesar el NWP no cambia nada y el margen estaba en el modelo",
                orden=0))
        else:
            out.append(Diagnostico(
                sintoma="error con clima observado parecido al error con pronóstico",
                medicion="1 - MAE(observado)/MAE(pronóstico)", valor=f"{frac:.0%}",
                umbral="<= 50 %", diagnostico="error del MODELO PV",
                aplicar=["features", "construcción de datos", "capacidad"],
                no_aplicar=["cambiar proveedor de clima"], orden=0))

    # --- 2. Sesgo contra dispersión.
    # La fila de varianza NO se puede leer sola: si casi todo el error es
    # importado del meteorológico, "dispersión alta" describe la incertidumbre
    # irreducible del pronóstico, no varianza del modelo, y entonces el
    # ensamble y la regularización no aplican. Verificado: sobre este modelo,
    # con 87 % de error importado, un ensamble de ocho ventanas contiguas dio
    # +0.31 kW contra una vara de 0.37 (sin efecto) y reducir capacidad empeoró
    # la validación. La predicción falsable de la fila de varianza falló, y la
    # conclusión correcta es que el límite no está en el modelo.
    importado_alto = (
        mae_con_observado is not None and (1.0 - mae_con_observado / max(mae, 1e-9)) > 0.5
    )
    razon = abs(sesgo) / max(mae, 1e-9)
    if razon > 0.40:
        out.append(Diagnostico(
            sintoma="sesgo grande respecto del MAE",
            medicion="|sesgo| / MAE", valor=f"{razon:.0%} (sesgo {sesgo:+.1f} kW)",
            umbral="> 40 %", diagnostico="error SISTEMÁTICO",
            aplicar=["features faltantes", "revisar construcción de datos",
                     "corrección de nivel", "normalización"],
            no_aplicar=["ensamble", "cambio de arquitectura"],
            si_acierto="corregir el nivel baja el MAE casi en la magnitud del sesgo",
            si_error="el MAE no se mueve y el sesgo reaparece en el siguiente bloque",
            orden=1))
    elif importado_alto:
        out.append(Diagnostico(
            sintoma="sesgo pequeño, dispersión alta, con el error mayormente importado",
            medicion="|sesgo| / MAE con fracción importada",
            valor=f"{razon:.0%} de sesgo, {1.0 - mae_con_observado / max(mae, 1e-9):.0%} importado",
            umbral="sesgo <= 40 % e importado > 50 %",
            diagnostico="dispersión IRREDUCIBLE dado el pronóstico",
            aplicar=["nada del lado del modelo PV",
                     "decirlo: el margen está en el insumo meteorológico"],
            no_aplicar=["ensamble", "regularización", "menos capacidad",
                        "más datos", "features nuevas", "arquitectura"],
            si_acierto="ensamble y regularización no mueven el MAE contra la vara",
            si_error="el ensamble sí baja el MAE: había varianza del modelo y esta "
                     "fila la estaba tapando",
            orden=1))
    else:
        out.append(Diagnostico(
            sintoma="sesgo pequeño, dispersión alta",
            medicion="|sesgo| / MAE", valor=f"{razon:.0%} (sesgo {sesgo:+.1f} kW)",
            umbral="<= 40 %", diagnostico="dominado por VARIANZA del modelo",
            aplicar=["ensamble", "parada temprana", "regularización",
                     "menos capacidad", "más datos"],
            no_aplicar=["buscar features nuevas"],
            si_acierto="promediar corridas o regularizar baja el MAE",
            si_error="el ensamble no mueve el MAE: el límite no es varianza del modelo",
            orden=1))

    # --- 3. Sobreajuste o subajuste
    if mae_entrenamiento is not None and mae_validacion is not None:
        r = mae_validacion / max(mae_entrenamiento, 1e-9)
        # Umbral 1.10, no 1.25. Cuando la mayor parte del error es irreducible
        # —aquí el 87 % viene del pronóstico— el sobreajuste queda diluido: un
        # modelo con 1500 iteraciones, claramente sobreajustado, mide 1.17 y el
        # sano 0.96. El umbral de la matriz está pensado para casos donde el
        # error del modelo domina; con error importado alto hay que bajarlo.
        if r > 1.10:
            out.append(Diagnostico(
                sintoma="error de entrenamiento muy por debajo del de validación",
                medicion="MAE(validación)/MAE(entrenamiento)", valor=f"{r:.2f}",
                umbral="> 1.25", diagnostico="SOBREAJUSTE",
                aplicar=["menos capacidad", "regularización", "parada temprana", "más datos"],
                no_aplicar=["más épocas", "red más grande"], orden=2))

    # --- 3bis. Objetivo desalineado: el pronóstico puntual no es el funcional
    # que minimiza la métrica. El MAE lo minimiza la MEDIANA condicional; un
    # modelo entrenado con pérdida cuadrática entrega la media, y entonces el
    # residuo tiene mediana distinta de cero aunque su media sea pequeña.
    # Es la primera fila de la matriz y no estaba implementada: la validación
    # contra un modelo de media inyectado a propósito no la detectaba.
    mediana_e = float(e.median())
    if abs(mediana_e) > 0.12 * mae and razon < 0.40:
        out.append(Diagnostico(
            sintoma="residuo con mediana lejos de cero y media cerca de cero",
            medicion="mediana(residuo) / MAE",
            valor=f"{mediana_e / mae:+.0%} (mediana {mediana_e:+.1f} kW, media {sesgo:+.1f})",
            umbral="|mediana| > 12 % del MAE con sesgo medio < 40 %",
            diagnostico="OBJETIVO DESALINEADO con la métrica",
            aplicar=["cambiar la función de pérdida al funcional que la métrica "
                     "minimiza (mediana para MAE, cuantil para penalidad asimétrica)"],
            no_aplicar=["todo lo demás, hasta resolver esto"],
            si_acierto="reentrenar con pérdida cuantílica baja el MAE sin tocar features",
            si_error="el MAE no cambia: el funcional ya era el correcto",
            orden=1))

    # A partir de aquí el residuo va SIN el sesgo global. Un error de nivel se
    # derrama sobre las filas de geometría y de censura: un sesgo de +25 kW
    # hacía disparar "objetivo censurado" y "horizonte" a la vez, porque a sol
    # bajo un desplazamiento constante es enorme en términos relativos. Primero
    # se corrige el nivel, después se mira la forma.
    # SIEMPRE, no solo cuando el sesgo cruza el umbral de diagnóstico. Las
    # filas siguientes son sobre la FORMA del residuo; el nivel es otra cosa y
    # se quita antes. Medido: un sesgo de +25 kW sobre un MAE de 52 queda en
    # 38 % —bajo el umbral del 40 % de la matriz, que no dispara— y aun así
    # hacía encender "objetivo censurado" y "horizonte" a la vez.
    e = e - sesgo

    # --- 4. Regresión a la media por la pérdida
    nub = j["kc"] < 0.45
    desp = j["kc"] > 0.85
    if nub.sum() > 100 and desp.sum() > 100:
        s_nub = float(e[nub].mean())
        s_desp = float(e[desp].mean())
        if s_nub > 0.08 * mae and s_desp < -0.08 * mae:
            out.append(Diagnostico(
                sintoma="sobrepronóstico en nublados y subpronóstico en despejados",
                medicion="sesgo por régimen de cielo",
                valor=f"nublado {s_nub:+.1f} kW / despejado {s_desp:+.1f} kW",
                umbral="signos opuestos y |sesgo| > 8 % del MAE",
                diagnostico="REGRESIÓN A LA MEDIA por la pérdida",
                aplicar=["pérdida cuantílica", "salida distribucional",
                         "índice de cielo despejado como objetivo"],
                no_aplicar=["más capacidad"],
                si_acierto="la pérdida cuantílica reduce el sesgo en ambos extremos a la vez",
                si_error="los sesgos por régimen no cambian: no es la pérdida, es una feature",
                orden=3))

    # --- 5. Objetivo censurado por el recorte
    # El residuo se condiciona a una variable EXÓGENA —la irradiancia en el
    # plano del arreglo—, NO al valor realizado. Condicionar en "las horas en
    # que la planta produjo mucho" garantiza sesgo negativo para cualquier
    # modelo imperfecto, por pura regresión a la media: se está seleccionando
    # sobre el resultado. La primera versión de este detector hacía eso y
    # reportaba censura con -71.5 kW de sesgo, además con el signo CONTRARIO al
    # del mecanismo que afirmaba: un objetivo censurado se SOBREpronostica,
    # porque el modelo predice el potencial sin techo.
    if "poa_wm2" in j:
        techo_poa = float(j["poa_wm2"].quantile(0.95))
        alto = j["poa_wm2"] > techo_poa
        if alto.sum() > 50:
            s_alto = float(e[alto].mean())
            pegados = float(
                (j.loc[alto, "real"] > 0.97 * meta.capacidad_ac_kw).mean()
            )
            if s_alto > 0.5 * mae and pegados > 0.2:
                out.append(Diagnostico(
                    sintoma="sobrepronóstico donde la irradiancia satura el inversor",
                    medicion="sesgo en el 5 % superior de irradiancia en plano, "
                             "con el objetivo pegado al techo",
                    valor=f"{s_alto:+.1f} kW; {pegados:.0%} de esas horas en el techo",
                    umbral="sesgo > 50 % del MAE y > 20 % de horas en el techo",
                    diagnostico="OBJETIVO CENSURADO por recorte",
                    aplicar=["modelo consciente de capacidad AC/DC",
                             "pérdida que respete el techo"],
                    no_aplicar=["más features meteorológicas"],
                    si_acierto="imponer el techo en la predicción borra el sesgo en esa banda",
                    si_error="el sesgo persiste: no es censura, es error de nivel",
                    orden=4))

    # --- 6. Error concentrado en ciertas horas
    por_hora = e.abs().groupby(j.index.hour).mean()
    if len(por_hora) > 4:
        conc = float(por_hora.max() / max(por_hora.median(), 1e-9))
        if conc > 2.0:
            out.append(Diagnostico(
                sintoma="error concentrado en ciertas horas",
                medicion="MAE máximo por hora / MAE mediano por hora",
                valor=f"{conc:.1f} (peor hora {int(por_hora.idxmax())} UTC)",
                umbral="> 2.0", diagnostico="GEOMETRÍA SOLAR o ALINEACIÓN",
                aplicar=["ángulo solar", "índice de cielo despejado",
                         "revisar convenciones horarias"],
                no_aplicar=["arquitectura"], orden=5))

    # --- 7. Error solo en ángulos solares bajos
    bajo = j["elevacion_sol"] < 15
    altoel = j["elevacion_sol"] > 35
    if bajo.sum() > 100 and altoel.sum() > 100:
        r_bajo = float(e[bajo].abs().mean() / max(j.loc[bajo, "real"].mean(), 1e-9))
        r_alto = float(e[altoel].abs().mean() / max(j.loc[altoel, "real"].mean(), 1e-9))
        if r_bajo > 2.0 * r_alto:
            out.append(Diagnostico(
                sintoma="error relativo mucho mayor a sol bajo",
                medicion="nMAE(elev<15°) / nMAE(elev>35°)", valor=f"{r_bajo / r_alto:.1f}",
                umbral="> 2.0", diagnostico="HORIZONTE, SOMBREADO o TRANSPOSICIÓN",
                aplicar=["perfil de horizonte", "ángulo de incidencia"],
                no_aplicar=["arquitectura"], orden=6))

    # --- 8. Error concentrado en ciertos días
    por_dia = e.abs().groupby(j.index.date).mean()
    if len(por_dia) > 30:
        umbral_d = por_dia.median() * 3
        malos = por_dia[por_dia > umbral_d]
        if len(malos) / len(por_dia) > 0.02:
            out.append(Diagnostico(
                sintoma="error concentrado en días puntuales",
                medicion="días con MAE > 3× la mediana diaria",
                valor=f"{len(malos)} de {len(por_dia)} ({len(malos) / len(por_dia):.1%})",
                umbral="> 2 % de los días", diagnostico="probablemente OPERATIVO",
                aplicar=["investigar paradas y limitaciones"],
                no_aplicar=["cualquier cambio al modelo"], orden=7))

    # --- 9. Deriva mes a mes
    por_mes = e.groupby(j.index.to_period("M")).mean()
    if len(por_mes) >= 4:
        pend = float(np.polyfit(np.arange(len(por_mes), dtype=float), por_mes.to_numpy(), 1)[0])
        if abs(pend) > 0.03 * mae:
            out.append(Diagnostico(
                sintoma="sesgo que deriva mes a mes",
                medicion="pendiente del sesgo mensual", valor=f"{pend:+.2f} kW/mes",
                umbral="|pendiente| > 3 % del MAE", diagnostico="DERIVA (suciedad o capacidad)",
                aplicar=["días desde el último lavado", "ventana móvil",
                         "normalizar por capacidad", "reentrenamiento"],
                no_aplicar=["reentrenar sin separar la causa",
                            "acumular datos antiguos sin normalizar"], orden=8))

    return sorted(out, key=lambda d: d.orden)


def informe(ds: list[Diagnostico]) -> str:
    if not ds:
        return "Sin diagnóstico: ninguna fila de la matriz aplica. El problema no está en el modelo."
    return "\n".join(d.texto() for d in ds)
