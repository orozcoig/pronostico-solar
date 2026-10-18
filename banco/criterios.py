"""Criterios de muerte, evaluables — Etapa 1 de la Fase 9.

Se pactan ANTES de empezar y se evalúan con números, no con criterio. Un
criterio de muerte que se decide después de ver los datos no es un criterio: es
una racionalización.

Cada criterio devuelve uno de tres estados:

    SIGUE      el proyecto continúa como estaba planteado
    REPLANTEA  el alcance cambia; hay que renegociar antes de seguir
    DETENTE    no hay proyecto; se dice y se para

El orden importa: las puertas de entrada se evalúan antes de cobrar la Etapa 1;
las de diagnóstico, durante; las de producto, al final. Un DETENTE temprano es
el resultado más barato que este proyecto puede producir.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Estado(Enum):
    SIGUE = "SIGUE"
    REPLANTEA = "REPLANTEA"
    DETENTE = "DETENTE"


@dataclass
class Criterio:
    id: str
    nombre: str
    medicion: str
    umbral: str
    estado: Estado
    valor: str
    consecuencia: str

    def linea(self) -> str:
        return (f"{self.id:<4}{self.estado.value:<11}{self.nombre:<42}"
                f"{self.valor:<28}{self.consecuencia}")


# ---------------------------------------------------------------- puertas

def m1_historia_minima(meses_medicion: float, resolucion_minutos: float) -> Criterio:
    """Sin medición horaria con doce meses no es un proyecto de pronóstico."""
    ok = meses_medicion >= 12 and resolucion_minutos <= 60
    return Criterio(
        "M1", "Medición horaria con >= 12 meses",
        "meses de medición y resolución nativa", ">= 12 meses y <= 60 min",
        Estado.SIGUE if ok else Estado.DETENTE,
        f"{meses_medicion:.0f} meses a {resolucion_minutos:.0f} min",
        "Se cotiza" if ok else "No es pronóstico operativo: decirlo antes de cotizar",
    )


def m2_archivo_de_pronostico(meses_archivo: float, meses_requeridos: float = 18) -> Criterio:
    """Entrenar con reanálisis o con la mejor corrida posterior no es opción."""
    ok = meses_archivo >= meses_requeridos
    return Criterio(
        "M2", "Archivo de pronóstico con profundidad",
        "meses de corridas archivadas", f">= {meses_requeridos:.0f} meses",
        Estado.SIGUE if ok else Estado.REPLANTEA,
        f"{meses_archivo:.0f} meses",
        "Se entrena con el archivo" if ok else
        "Cambia el cronograma: hay que acumular archivo. NO sustituir por reanálisis",
    )


def m3_fase1_cerrada(hora_emision: bool, horizonte: bool, penalidad: bool) -> Criterio:
    """Sin horizonte y sin penalidad no hay métrica contra la cual mejorar."""
    faltan = [n for n, v in (("hora de emisión", hora_emision),
                             ("horizonte", horizonte),
                             ("penalidad", penalidad)) if not v]
    return Criterio(
        "M3", "Fase 1 cerrada", "hora de emisión, horizonte y penalidad definidos",
        "las tres",
        Estado.SIGUE if not faltan else Estado.DETENTE,
        "completa" if not faltan else f"faltan: {', '.join(faltan)}",
        "Se puede medir mejora" if not faltan else
        "No se puede definir la métrica: no se cotiza Etapa 2 ni se promete precisión",
    )


# ------------------------------------------------------------- diagnóstico

def m4_error_importado(fraccion_importada: float, umbral: float = 0.80) -> Criterio:
    """Si casi todo el error es del meteorólogo, el alcance no es el modelo."""
    alto = fraccion_importada > umbral
    return Criterio(
        "M4", "Fracción de error importada del meteorológico",
        "1 - MAE(clima observado)/MAE(clima pronosticado)", f"<= {umbral:.0%}",
        Estado.REPLANTEA if alto else Estado.SIGUE,
        f"{fraccion_importada:.0%}",
        "El margen está en el modelo" if not alto else
        "Replantear hacia el insumo meteorológico; no vender trabajo de modelado",
    )


def m5_margen_disponible(mae_actual: float, mae_techo: float,
                         umbral_relativo: float = 0.10) -> Criterio:
    """Cuánta mejora existe realmente, medida y no supuesta."""
    margen = (mae_actual - mae_techo) / max(mae_actual, 1e-9)
    ok = margen >= umbral_relativo
    return Criterio(
        "M5", "Margen entre error actual y techo alcanzable",
        "(MAE actual - MAE con clima observado) / MAE actual",
        f">= {umbral_relativo:.0%}",
        Estado.SIGUE if ok else Estado.DETENTE,
        f"{margen:.0%} ({mae_actual:.1f} -> {mae_techo:.1f} kW)",
        "Hay margen técnico" if ok else
        "No hay mejora en venta del lado del modelo: decirlo y no cotizar Etapa 2",
    )


def m6_calidad_del_dato(fraccion_dias_inservibles: float,
                        registro_eventos: bool, umbral: float = 0.10) -> Criterio:
    """Dato malo y sin bitácora: el diagnóstico deja de ser confiable."""
    malo = fraccion_dias_inservibles > umbral
    return Criterio(
        "M6", "Días inservibles y registro de eventos",
        "fracción de días con huecos, congelados o anómalos",
        f"<= {umbral:.0%} o con bitácora",
        Estado.SIGUE if not malo else (
            Estado.REPLANTEA if registro_eventos else Estado.DETENTE),
        f"{fraccion_dias_inservibles:.0%}, bitácora={'sí' if registro_eventos else 'no'}",
        "Dato utilizable" if not malo else (
            "Primero saneamiento de datos, luego pronóstico" if registro_eventos else
            "Sin bitácora no se separa falla operativa de día difícil: no es diagnosticable"),
    )


def m7_historia_vs_falla(meses: float, falla_objetivo: str) -> Criterio:
    """Lo que el cliente quiere diagnosticar, ¿cabe en su historia?

    Medido en el banco: nueve de las diez fallas se diagnostican con seis
    meses; la deriva por suciedad necesita veinticuatro, porque separar una
    tendencia monótona de la estacionalidad bimodal exige dos ciclos completos.
    """
    requeridos = {"deriva_suciedad": 24}.get(falla_objetivo, 6)
    ok = meses >= requeridos
    return Criterio(
        "M7", "Historia suficiente para la falla buscada",
        "meses disponibles vs meses requeridos por esa falla",
        f">= {requeridos} meses para '{falla_objetivo}'",
        Estado.SIGUE if ok else Estado.REPLANTEA,
        f"{meses:.0f} de {requeridos} meses",
        "Diagnosticable" if ok else
        "No concluyente para esa falla: reportar como tal, NUNCA como ausencia",
    )


def m8_punto_ciego(hallazgos: int, queja_del_cliente: str,
                   puntos_ciegos: tuple = ("perdida_desalineada", "features_faltantes")) -> Criterio:
    """El agente no vio nada, ¿pero podía ver lo que el cliente pregunta?

    Validado contra seis casos inyectados en el modelo: cuatro correctos y dos
    puntos ciegos medidos. Un 'no encontré nada' sobre un punto ciego no es un
    resultado negativo, es ausencia de medición.
    """
    ciego = hallazgos == 0 and queja_del_cliente in puntos_ciegos
    return Criterio(
        "M8", "El silencio del agente, ¿es informativo?",
        "hallazgos vs puntos ciegos conocidos del agente", "la queja no es punto ciego",
        Estado.SIGUE if not ciego else Estado.REPLANTEA,
        f"{hallazgos} hallazgos, queja='{queja_del_cliente}'",
        "El silencio es informativo" if not ciego else
        "El agente no puede ver eso: NO concluir que no hay problema",
    )


# ----------------------------------------------------------------- producto

def m9_supera_lineas_base(diferencia_vs_mejor_base: float, vara: float) -> Criterio:
    """Si no supera la vara, no hay producto. Se dice sin adornos."""
    ok = diferencia_vs_mejor_base < -vara
    return Criterio(
        "M9", "El modelo supera la mejor línea base contra la vara",
        "diferencia pareada vs vara = 2 x EE (bootstrap de bloques 3-7 d)",
        "|diferencia| > vara y a favor del modelo",
        Estado.SIGUE if ok else Estado.DETENTE,
        f"dif {diferencia_vs_mejor_base:+.2f} kW, vara {vara:.2f}",
        "Hay producto" if ok else
        "No supera la vara: no hay producto vendible; entregar la línea base y decirlo",
    )


def m11_rol_expuesto_al_error(rol: str) -> Criterio:
    """¿El rol del cliente paga por equivocarse hora a hora?

    Verificado contra la regulación colombiana vigente en octubre de 2026 (ver
    FASE2_COSTO_DEL_ERROR.md). Un autogenerador a pequeña escala —hasta 1 MW—
    se liquida por período de facturación, no por hora: su error horario no
    tiene precio regulatorio. Equivocarse a las 10 y compensarse a las 3 cuesta
    cero. Un contrato privado puede imponer una penalidad que la regulación no
    impone, y eso cambiaría el veredicto; por eso es REPLANTEA y no DETENTE.
    """
    expuestos = {
        "generador_no_despachado": "diferencial bolsa-contrato por hora",
        "generador_despachado": "franjas de desviación con banda muerta",
        "usuario_no_regulado": "diferencial sobre la cantidad liquidada",
    }
    exp = rol in expuestos
    return Criterio(
        "M11", "El rol paga por el error horario",
        "régimen de liquidación aplicable al rol", "liquidación horaria, no mensual",
        Estado.SIGUE if exp else Estado.REPLANTEA,
        f"{rol}: {expuestos.get(rol, 'liquidación por período de facturación')}",
        "El error tiene precio de mercado" if exp else
        "Sin exposición horaria: buscar valor operativo o un contrato que lo penalice, "
        "o no vender pronóstico a este rol",
    )


def m10_valor_economico(valor_anual_cop: float | None, costo_etapa2_cop: float,
                        multiplo: float = 3.0) -> Criterio:
    """El valor de reducir el error debe justificar la Etapa 2 con holgura."""
    if valor_anual_cop is None:
        return Criterio(
            "M10", "Valor anual vs costo de la Etapa 2",
            "valor de reducir el error 10-30 % / costo de la Etapa 2",
            f">= {multiplo:.0f}x", Estado.REPLANTEA, "no calculable",
            "Bloqueado por la penalidad y por qué cantidad se liquida (Fase 1)",
        )
    r = valor_anual_cop / max(costo_etapa2_cop, 1e-9)
    return Criterio(
        "M10", "Valor anual vs costo de la Etapa 2",
        "valor anual / costo de la Etapa 2", f">= {multiplo:.0f}x",
        Estado.SIGUE if r >= multiplo else Estado.DETENTE, f"{r:.1f}x",
        "Se cotiza la Etapa 2" if r >= multiplo else
        "El valor no justifica el motor: entregar el diagnóstico y parar",
    )


def tabla(criterios: list[Criterio]) -> str:
    cab = f"{'ID':<4}{'ESTADO':<11}{'CRITERIO':<42}{'VALOR':<28}CONSECUENCIA"
    cuerpo = "\n".join(c.linea() for c in criterios)
    peor = min(criterios, key=lambda c: ["DETENTE", "REPLANTEA", "SIGUE"].index(c.estado.value))
    return f"{cab}\n{'-' * 150}\n{cuerpo}\n\nVEREDICTO: {peor.estado.value} — {peor.id}: {peor.consecuencia}"
