"""Catálogo de fallas inyectables — Fase 3.3.

Cada falla se inyecta de a una, con magnitud conocida, y deja constancia en un
manifiesto. El manifiesto es la verdad contra la cual se califica al agente en
3.4: ¿nombró la falla?, ¿nombró la medición que la delata?, ¿rechazó las
técnicas que no aplican?

**La capa de inyección es parte de la definición de la falla, no un detalle de
implementación.**

  * Capa VERDAD: la falla es pérdida física real. La planta de verdad produce
    menos. Un modelo correcto *debe* aprenderla, y la acción correcta puede ser
    operativa (lavar, revisar el inversor), no de modelado.
  * Capa MEDICIÓN: la falla es un artefacto del registro. La planta produjo lo
    que produjo; lo que está mal es lo que quedó escrito. Un modelo que la
    aprende está aprendiendo un bug del historiador.

Confundirlas produce el peor error posible del proyecto: "mejorar" el modelo
ajustándolo a un defecto de instrumentación.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import numpy as np
import pandas as pd

from .contrato import POTENCIA_AC, MetadatosSitio
from .planta import ParametrosPlanta


class Capa(Enum):
    VERDAD = "verdad"
    MEDICION = "medicion"
    # Tercera capa: la falla no está en la planta ni en el registro, sino en el
    # insumo meteorológico. Su firma distintiva es que el error NO baja al
    # alimentar el modelo con clima observado.
    PRONOSTICO = "pronostico"


class Falla(Protocol):
    """Interfaz de una falla inyectable."""

    nombre: str
    capa: Capa

    def modificar_planta(
        self, params: ParametrosPlanta, indice: pd.DatetimeIndex, meta: MetadatosSitio
    ) -> tuple[ParametrosPlanta, dict[str, np.ndarray]]:
        """Capa VERDAD: params ajustados y series por paso de tiempo.

        Claves admitidas: suciedad, disponibilidad, limite_ac_kw, capacidad_dc_kwp.
        """
        ...

    def modificar_medicion(self, df: pd.DataFrame, meta: MetadatosSitio) -> pd.DataFrame:
        """Capa MEDICIÓN: transforma la serie registrada."""
        ...

    def modificar_pronostico(self, params):
        """Capa PRONÓSTICO: degrada el insumo meteorológico."""
        ...

    def manifiesto(self) -> dict:
        """Verdad conocida: qué se inyectó, con qué magnitud, y qué debe detectarse."""
        ...


class _Base:
    """Comportamiento neutro en ambas capas; cada falla sobreescribe la suya."""

    def modificar_planta(self, params, indice, meta):
        return params, {}

    def modificar_medicion(self, df, meta):
        return df

    def modificar_pronostico(self, params):
        return params


# --------------------------------------------------------------------------
# 1. Desfase horario — capa MEDICIÓN
# --------------------------------------------------------------------------

@dataclass
class DesfaseHorario(_Base):
    """Reloj mal configurado o zona horaria mal aplicada al exportar.

    Los desfases legítimos en Colombia son discretos: 5 h (UTC tomado como hora
    local, no hay horario de verano), 1 h (etiqueta de inicio contra etiqueta de
    fin) y la numeración 1–24 de XM contra 0–23. Cualquier otro valor es otra
    cosa y hay que investigarlo, no corregirlo.

    `desde`/`hasta` acotan la ventana afectada: un reloj que se reinicia a mitad
    de serie es más realista que uno mal desde el día uno, y además es lo que
    hace visible el punto de cambio.

    Convención: `horas > 0` significa que el dato aparece etiquetado MÁS TARDE
    de lo que ocurrió, es decir medicion[t] = verdad[t - horas].
    """

    horas: float = 1.0
    desde: dt.date | None = None
    hasta: dt.date | None = None
    nombre: str = field(default="desfase_horario", init=False)
    capa: Capa = field(default=Capa.MEDICION, init=False)

    def modificar_medicion(self, df: pd.DataFrame, meta: MetadatosSitio) -> pd.DataFrame:
        salida = df.copy()
        idx = salida.index
        m = np.ones(len(idx), dtype=bool)
        if self.desde is not None:
            m &= idx >= pd.Timestamp(self.desde, tz="UTC")
        if self.hasta is not None:
            m &= idx < pd.Timestamp(self.hasta, tz="UTC")
        desplazada = salida[POTENCIA_AC].shift(freq=pd.Timedelta(hours=self.horas))
        salida.loc[m, POTENCIA_AC] = desplazada.reindex(idx)[m].to_numpy()
        return salida

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "desfase_mediodia_solar",
            "falla": self.nombre,
            "capa": self.capa.value,
            "magnitud": {"horas": self.horas},
            "ventana": [str(self.desde), str(self.hasta)],
            "debe_detectar": "error concentrado y simétrico en salida y puesta de sol",
            "medicion_que_la_delata": "mediodía solar observado vs tránsito solar calculado",
            "medicion_prohibida": "centro de masa de la curva diaria (la convección "
                                  "vespectina del Aburrá lo corre 20–40 min por climatología)",
            "tecnica_correcta": "revisar convenciones horarias y realinear",
            "tecnica_incorrecta": "cambiar arquitectura del modelo; agregar features",
        }


# --------------------------------------------------------------------------
# 2. Recorte por límite del inversor — capa VERDAD
# --------------------------------------------------------------------------

@dataclass
class RecorteInversor(_Base):
    """El inversor limita por debajo de lo que dice la placa.

    No es ruido: es un objetivo CENSURADO. La planta podría producir más y no lo
    hace. El modelo que no conoce el techo sobrepronostica exactamente en las
    horas de mayor generación, que son las que más pesan en pesos.

    Con `limite_real_kw = None` la falla es la censura honesta: el inversor
    recorta en su límite declarado, y lo que falla es que el modelo lo ignore.
    Con un valor menor, además hay discrepancia entre placa y equipo.
    """

    limite_real_kw: float | None = None
    nombre: str = field(default="recorte_inversor", init=False)
    capa: Capa = field(default=Capa.VERDAD, init=False)

    def modificar_planta(self, params, indice, meta):
        from dataclasses import replace

        limite = self.limite_real_kw if self.limite_real_kw is not None else meta.capacidad_ac_kw
        return replace(params, limite_ac_real_kw=limite), {}

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "firma_recorte",
            "falla": self.nombre,
            "capa": self.capa.value,
            "magnitud": {"limite_real_kw": self.limite_real_kw},
            "debe_detectar": "error concentrado en el techo de potencia",
            "medicion_que_la_delata": "fracción de pasos diurnos en una meseta de potencia "
                                      "y distribución del error por decil de generación",
            "tecnica_correcta": "modelo consciente de capacidad AC/DC; pérdida que respete el techo",
            "tecnica_incorrecta": "más features meteorológicas",
        }


# --------------------------------------------------------------------------
# 3. Deriva por suciedad con lavados — capa VERDAD
# --------------------------------------------------------------------------

@dataclass
class DerivaSuciedad(_Base):
    """Ensuciamiento progresivo con reinicios en cada lavado.

    Firma: sesgo negativo creciente, en diente de sierra. A 15° de inclinación
    el autolavado por lluvia es marginal, así que la tasa queda en rango amplio
    declarado (0.2–1.0 %/mes) y es un parámetro de barrido, no un dato.

    Es la falla que fija el mínimo de historia: separar una tendencia monótona
    de la estacionalidad bimodal exige dos ciclos completos, y el diente de
    sierra exige al menos tres lavados. De ahí los 24 meses.
    """

    tasa_mensual: float = 0.006        # pérdida fraccional adicional por mes
    perdida_maxima: float = 0.09       # saturación: el polvo deja de acumularse
    lavados: tuple[dt.date, ...] = ()
    residual_tras_lavado: float = 0.005
    nombre: str = field(default="deriva_suciedad", init=False)
    capa: Capa = field(default=Capa.VERDAD, init=False)

    def modificar_planta(self, params, indice, meta):
        dias = (indice - indice[0]).total_seconds().to_numpy() / 86400.0
        cortes = np.array(
            [0.0]
            + [
                (pd.Timestamp(d, tz="UTC") - indice[0]).total_seconds() / 86400.0
                for d in sorted(self.lavados)
            ]
        )
        ultimo = np.searchsorted(cortes, dias, side="right") - 1
        dias_desde_lavado = dias - cortes[ultimo]
        base = np.where(ultimo > 0, self.residual_tras_lavado, params.suciedad_base)
        suciedad = np.minimum(
            base + self.tasa_mensual * dias_desde_lavado / 30.44, self.perdida_maxima
        )
        return params, {"suciedad": suciedad}

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "tendencia_desempeno",
            "falla": self.nombre,
            "capa": self.capa.value,
            "magnitud": {
                "tasa_mensual": self.tasa_mensual,
                "perdida_maxima": self.perdida_maxima,
                "lavados": [str(d) for d in self.lavados],
            },
            "debe_detectar": "sesgo negativo creciente con reinicios",
            "medicion_que_la_delata": "índice de desempeño mensual (potencia medida sobre "
                                      "esperada por POA) con los días recortados excluidos",
            "tecnica_correcta": "feature de días desde el último lavado; ventana móvil",
            "tecnica_incorrecta": "reentrenar sin separar la causa",
            "minimo_de_historia_meses": 24,
        }


# --------------------------------------------------------------------------
# 4. Paradas y mantenimientos — capa VERDAD
# --------------------------------------------------------------------------

@dataclass
class ParadasMantenimiento(_Base):
    """Planta fuera de servicio en ventanas conocidas.

    Produce DÍAS COMPLETOS ANÓMALOS, no días difíciles de pronosticar. La
    distinción es la que manda la Fase 7: ante error concentrado en ciertos
    días la acción correcta es investigar operación, y NO cambiar el modelo.
    Un agente que responda con arquitectura o features aquí, reprueba.
    """

    ventanas: tuple[tuple[dt.datetime, dt.datetime], ...] = ()
    nombre: str = field(default="paradas_mantenimiento", init=False)
    capa: Capa = field(default=Capa.VERDAD, init=False)

    def modificar_planta(self, params, indice, meta):
        disp = np.ones(len(indice))
        for a, b in self.ventanas:
            disp[(indice >= pd.Timestamp(a, tz="UTC")) & (indice < pd.Timestamp(b, tz="UTC"))] = 0.0
        return params, {"disponibilidad": disp}

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "dias_anomalos",
            "falla": self.nombre, "capa": self.capa.value,
            "magnitud": {"ventanas": [[str(a), str(b)] for a, b in self.ventanas]},
            "debe_detectar": "días completos anómalos, no días difíciles",
            "medicion_que_la_delata": "razón energía medida / esperada por día; cae a ~0",
            "tecnica_correcta": "investigar paradas y limitaciones; excluir o marcar esos días",
            "tecnica_incorrecta": "CUALQUIER cambio al modelo",
        }


# --------------------------------------------------------------------------
# 5. Limitación de potencia por el operador — capa VERDAD
# --------------------------------------------------------------------------

@dataclass
class LimitacionOperador(_Base):
    """Techo de potencia VARIABLE impuesto por despacho, no explicado por clima.

    Se distingue del recorte de inversor en que el techo cambia de día a día.
    Un techo fijo se puede meter en el modelo como capacidad; uno variable no:
    sin la señal del operador, es irreducible, y decirlo vale más que intentarlo.
    """

    fraccion_dias: float = 0.08
    techo_fraccion: tuple[float, float] = (0.45, 0.80)
    semilla: int = 11
    nombre: str = field(default="limitacion_operador", init=False)
    capa: Capa = field(default=Capa.VERDAD, init=False)

    def modificar_planta(self, params, indice, meta):
        rng = np.random.default_rng(self.semilla)
        fechas = pd.Index(indice.date)
        dias = pd.Index(sorted(set(fechas)))
        techos = pd.Series(float(meta.capacidad_ac_kw), index=dias)
        n = max(1, int(len(dias) * self.fraccion_dias))
        elegidos = rng.choice(dias.to_numpy(), size=n, replace=False)
        techos.loc[elegidos] = meta.capacidad_ac_kw * rng.uniform(*self.techo_fraccion, size=n)
        self._dias_limitados = sorted(str(d) for d in elegidos)
        return params, {"limite_ac_kw": techos.reindex(fechas).to_numpy()}

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "techo_variable",
            "falla": self.nombre, "capa": self.capa.value,
            "magnitud": {"fraccion_dias": self.fraccion_dias, "techo_fraccion": self.techo_fraccion},
            "debe_detectar": "techo variable no explicado por clima",
            "medicion_que_la_delata": "dispersión del máximo diario de potencia en días de alta irradiancia",
            "tecnica_correcta": "modelar lo que va a entregar, no lo que podría producir; dos modelos",
            "tecnica_incorrecta": "más features meteorológicas; más capacidad",
        }


# --------------------------------------------------------------------------
# 6. Orientación declarada distinta de la real — capa VERDAD
# --------------------------------------------------------------------------

@dataclass
class OrientacionDeclarada(_Base):
    """El arreglo está construido distinto de lo que dicen los metadatos.

    A 15 grados de inclinación esta falla es CASI INDETECTABLE: un error de
    azimut de 30 grados desplaza la normal del arreglo apenas 3.9 grados, y el
    efecto anual en el plano del arreglo queda por debajo del 1 %. La conclusión
    esperada sobre la planta de referencia es "no identificable"; sobre el
    gemelo de 30 grados, sí. Es la prueba de contención más exigente del banco,
    porque aquí SÍ hay falla inyectada y la respuesta correcta sigue siendo que
    no se puede afirmar.
    """

    inclinacion_real: float | None = None
    azimut_real: float | None = None
    nombre: str = field(default="orientacion_declarada", init=False)
    capa: Capa = field(default=Capa.VERDAD, init=False)

    def modificar_planta(self, params, indice, meta):
        from dataclasses import replace
        return replace(
            params,
            inclinacion_real_grados=self.inclinacion_real,
            azimut_real_grados=self.azimut_real,
        ), {}

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "asimetria_manana_tarde",
            "falla": self.nombre, "capa": self.capa.value,
            "magnitud": {"inclinacion_real": self.inclinacion_real, "azimut_real": self.azimut_real},
            "debe_detectar": "asimetría mañana/tarde del error",
            "medicion_que_la_delata": "razón de energía mañana/tarde medida contra esperada",
            "tecnica_correcta": "corregir la geometría en metadatos y recalcular el plano del arreglo",
            "tecnica_incorrecta": "arquitectura del modelo",
            "advertencia": "a baja inclinación puede no ser identificable; esa es la respuesta correcta",
        }


# --------------------------------------------------------------------------
# 7. Sesgo del modelo meteorológico — capa PRONÓSTICO
# --------------------------------------------------------------------------

@dataclass
class SesgoMeteorologico(_Base):
    """El insumo meteorológico viene sesgado. Ni la planta ni el registro fallan.

    Firma inconfundible: el error NO baja al alimentar el modelo con clima
    observado. Es la fila de la Fase 7 que separa "seguir optimizando el modelo
    PV" (inútil aquí) de "cambiar o post-procesar el proveedor" (lo correcto).
    """

    factor_sesgo: float = 3.0
    nombre: str = field(default="sesgo_meteorologico", init=False)
    capa: Capa = field(default=Capa.PRONOSTICO, init=False)

    def modificar_pronostico(self, params):
        from dataclasses import replace
        return replace(
            params,
            sesgo_nublado=params.sesgo_nublado * self.factor_sesgo,
            sesgo_despejado=params.sesgo_despejado * self.factor_sesgo,
        )

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "techo_alcanzable",
            "falla": self.nombre, "capa": self.capa.value,
            "magnitud": {"factor_sesgo": self.factor_sesgo},
            "debe_detectar": "error alto que NO baja con clima observado",
            "medicion_que_la_delata": "error con clima pronosticado vs error con clima observado",
            "tecnica_correcta": "post-proceso del NWP, mezcla de fuentes, ensamble, salida probabilística",
            "tecnica_incorrecta": "seguir optimizando el modelo PV; más features de planta",
        }


# --------------------------------------------------------------------------
# 8. Huecos y valores pegados — capa MEDICIÓN
# --------------------------------------------------------------------------

@dataclass
class HuecosYPegados(_Base):
    """El historiador pierde datos y a veces repite el último valor.

    El valor pegado es más peligroso que el hueco: un hueco se ve, un valor
    congelado pasa por dato. Firma: varianza nula por tramos en horas de sol.

    LÍMITE CONOCIDO, medido en el banco: un valor congelado EN CERO durante
    horas de sol es indistinguible de una parada de planta usando solo la serie
    de potencia. Las dos dan energía diaria baja y varianza nula. Separarlas
    exige información externa —bandera de estado del inversor, bitácora de
    eventos—, que es justo para lo que existe `eventos()` en el contrato, y por
    lo que un cliente sin registro de paradas tiene un diagnóstico más caro.
    Esta falla congela en valores NO triviales a propósito, para probar lo que
    dice probar; el congelamiento en cero es otra falla y necesita otro insumo.
    """

    fraccion_huecos: float = 0.02
    n_tramos_pegados: int = 8
    duracion_pegado_h: float = 9.0
    semilla: int = 23
    nombre: str = field(default="huecos_y_pegados", init=False)
    capa: Capa = field(default=Capa.MEDICION, init=False)

    def modificar_medicion(self, df, meta):
        rng = np.random.default_rng(self.semilla)
        s = df.copy()
        y = s[POTENCIA_AC].to_numpy().copy()
        n = len(y)
        pasos = max(1, int(self.duracion_pegado_h * 12))
        # Solo se congela en puntos con producción apreciable: ver LÍMITE
        # CONOCIDO en el docstring.
        candidatos = np.flatnonzero(y[: max(1, n - pasos)] > 0.10 * meta.capacidad_ac_kw)
        if len(candidatos):
            for i in rng.choice(candidatos, size=min(self.n_tramos_pegados, len(candidatos)),
                                replace=False):
                y[i : i + pasos] = y[i]
        n_h = int(n * self.fraccion_huecos)
        bloque = max(1, pasos // 3)
        for _ in range(max(1, n_h // bloque)):
            i = int(rng.integers(0, max(1, n - bloque)))
            y[i : i + bloque] = np.nan
        s[POTENCIA_AC] = y
        return s

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "rachas_pegadas",
            "falla": self.nombre, "capa": self.capa.value,
            "magnitud": {"fraccion_huecos": self.fraccion_huecos,
                         "n_tramos_pegados": self.n_tramos_pegados,
                         "duracion_pegado_h": self.duracion_pegado_h},
            "debe_detectar": "discontinuidades y varianza nula por tramos",
            "medicion_que_la_delata": "rachas de diferencia exactamente cero en horas de sol",
            "tecnica_correcta": "control de calidad y exclusión antes de entrenar",
            "tecnica_incorrecta": "imputar y seguir; entrenar sobre el tramo pegado",
        }


# --------------------------------------------------------------------------
# 9. Ampliación de capacidad a mitad de serie — capa VERDAD
# --------------------------------------------------------------------------

@dataclass
class AmpliacionCapacidad(_Base):
    """Entran módulos e inversores nuevos; los metadatos siguen diciendo lo viejo.

    El objetivo cambia de nivel. Acumular datos antiguos sin normalizar por
    capacidad arrastra el modelo hacia una planta que ya no existe.
    """

    fecha: dt.date | None = None
    factor: float = 1.30
    nombre: str = field(default="ampliacion_capacidad", init=False)
    capa: Capa = field(default=Capa.VERDAD, init=False)

    def modificar_planta(self, params, indice, meta):
        corte = pd.Timestamp(self.fecha, tz="UTC")
        f = np.where(indice >= corte, self.factor, 1.0)
        return params, {
            "capacidad_dc_kwp": meta.capacidad_dc_kwp * f,
            "limite_ac_kw": meta.capacidad_ac_kw * f,
        }

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "salto_de_nivel",
            "falla": self.nombre, "capa": self.capa.value,
            "magnitud": {"fecha": str(self.fecha), "factor": self.factor},
            "debe_detectar": "salto de nivel; deriva del objetivo",
            "medicion_que_la_delata": "salto en el índice de desempeño mensual",
            "tecnica_correcta": "normalizar por capacidad; ventana móvil; reentrenamiento",
            "tecnica_incorrecta": "acumular datos antiguos sin normalizar",
        }


# --------------------------------------------------------------------------
# 10. Sombreado de horizonte — capa VERDAD
# --------------------------------------------------------------------------

@dataclass
class SombreadoHorizonte(_Base):
    """Obstrucción mayor que la del perfil declarado en la línea base.

    La línea base del escenario limpio YA tiene horizonte urbano moderado: en
    cubierta del Valle de Aburrá el horizonte plano no existe. La falla es una
    desviación respecto de ese perfil, no la presencia de horizonte.
    """

    perfil: dict[float, float] | None = None
    nombre: str = field(default="sombreado_horizonte", init=False)
    capa: Capa = field(default=Capa.VERDAD, init=False)

    def modificar_planta(self, params, indice, meta):
        from dataclasses import replace
        perfil = self.perfil or {0: 6.0, 45: 12.0, 90: 24.0, 135: 14.0,
                                 180: 6.0, 225: 13.0, 270: 25.0, 315: 12.0, 360: 6.0}
        return replace(params, horizonte=dict(perfil)), {}

    def manifiesto(self) -> dict:
        return {
            "detector_esperado": "razon_por_elevacion",
            "falla": self.nombre, "capa": self.capa.value,
            "magnitud": {"perfil": self.perfil or "obstruccion al oriente y occidente ~24-25 grados"},
            "debe_detectar": "error solo en ángulos solares bajos",
            "medicion_que_la_delata": "razón medida/esperada por banda de elevación solar",
            "tecnica_correcta": "perfil de horizonte; ángulo de incidencia",
            "tecnica_incorrecta": "arquitectura del modelo",
        }


# --------------------------------------------------------------------------
# Escenarios
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Escenario:
    nombre: str
    sitio_id: str
    fallas: tuple = ()
    nota: str = ""

    def manifiesto(self, inicio: dt.date, fin: dt.date) -> dict:
        return {
            "escenario": self.nombre,
            "sitio": self.sitio_id,
            "ventana": [str(inicio), str(fin)],
            "nota": self.nota,
            "n_fallas": len(self.fallas),
            "fallas": [f.manifiesto() for f in self.fallas],
        }


def escenarios_base(inicio: dt.date, fin: dt.date) -> dict[str, Escenario]:
    """Escenarios de la primera tanda, uno por falla más el control negativo."""
    medio = inicio + (fin - inicio) / 2
    return {
        # 3.5 — control negativo. Conclusión esperada: no hay nada que corregir.
        "limpio": Escenario(
            "limpio", "med-ref-500",
            nota="Sin falla inyectada. Un agente que encuentra algo que arreglar aquí, no sirve.",
        ),
        "desfase_1h": Escenario(
            "desfase_1h", "med-ref-500",
            (DesfaseHorario(horas=1.0, desde=medio),),
            nota="Etiqueta de inicio contra etiqueta de fin, desde mitad de serie.",
        ),
        "desfase_utc": Escenario(
            "desfase_utc", "med-ref-500",
            (DesfaseHorario(horas=-5.0),),
            nota="UTC tomado como hora local en toda la serie.",
        ),
        # En la planta de referencia el recorte es 0.04 % de la energía: por
        # debajo de detección. Va sobre el gemelo de DC/AC alto.
        "recorte": Escenario(
            "recorte", "med-ref-560-dcac140",
            (RecorteInversor(),),
            nota="Objetivo censurado; el techo declarado es el real.",
        ),
        "recorte_oculto": Escenario(
            "recorte_oculto", "med-ref-560-dcac140",
            (RecorteInversor(limite_real_kw=340.0),),
            nota="El equipo limita 60 kW por debajo de la placa.",
        ),
        "suciedad": Escenario(
            "suciedad", "med-ref-500",
            (DerivaSuciedad(
                tasa_mensual=0.006,
                lavados=(dt.date(2023, 7, 1), dt.date(2024, 1, 15), dt.date(2024, 7, 1)),
            ),),
            nota="0.6 %/mes con tres lavados.",
        ),
    }
