"""Mediciones diagnósticas — la vara del criterio de aprobación 3.4.

El agente no aprueba por "encontrar algo": aprueba por nombrar la falla Y la
medición que la delata. Estas son esas mediciones. Cada una devuelve un número
con un umbral, no una impresión.

Las tres existen también como rutina publicada e independiente en PVAnalytics
(`quality.time.shifts_ruptures`, `features.clipping`) y RdTools (ensuciamiento).
Que haya dos implementaciones independientes de cada detector es deliberado: una
coincidencia entre ambas sobre una falla de magnitud conocida es evidencia; una
sola implementación propia de acuerdo consigo misma, no.

RESULTADO DEL CRUCE (24 meses, planta de referencia)

  desfase  inyectado -300 min -> propio -300.8 | pvanalytics -300.0   coinciden
           inyectado  +60 min -> propio  +60.1 | pvanalytics  +60.0   coinciden
  recorte  los cuatro escenarios del barrido DC/AC coinciden con clipping.geometric
  suciedad inyectado -0.600 %/mes -> propio -0.593 | RdTools SRR -0.683

Dos cosas que el cruce dejó ver y que conviene no olvidar:

  * El intervalo de confianza del SRR de RdTools (-0.713, -0.652) NO contiene el
    valor verdadero -0.600. Es un intervalo de repetibilidad del remuestreo, no
    de exactitud contra la verdad. Reportárselo a un cliente como margen de
    error del ensuciamiento sería exagerar la precisión.
  * Sobre la serie LIMPIA, RdTools reporta -0.023 %/mes con intervalo que excluye
    el cero: ajusta un perfil de ensuciamiento siempre, porque no tiene modo
    "aquí no hay nada". Sirve para estimar magnitud una vez establecida la
    presencia; no sirve como detector de sí/no sin un umbral encima. Ese -0.023
    %/mes es el piso de ruido empírico de este sitio y es el umbral a usar.

ADVERTENCIA sobre `indice_desempeno_mensual`: en el banco la potencia esperada
sale del mismo simulador que generó la verdad, así que el detector trabaja con
una referencia perfecta que NO va a tener con datos reales. En campo esa
referencia hay que construirla con un modelo físico ajustado a los datos, y su
error propio se suma al del diagnóstico. El desempeño medido aquí es una cota
superior.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pvlib.location import Location
from pvlib.solarposition import get_solarposition

from .contrato import POTENCIA_AC, MetadatosSitio


def desfase_mediodia_solar(
    generacion: pd.DataFrame, meta: MetadatosSitio, umbral_kw: float = 5.0
) -> pd.DataFrame:
    """Desfase diario entre el mediodía observado y el tránsito solar calculado.

    El mediodía observado es el punto medio entre el primer y el último paso con
    potencia por encima del umbral: salida y puesta vistas por la planta.

    **NO se usa centro de masa de la curva.** En el Aburrá la convección
    vespertina corre la curva entre 20 y 40 minutos por climatología real, y eso
    se leería como un desfase que no existe. El punto medio entre salida y
    puesta es insensible a cómo se reparte la energía dentro del día: es ancla
    geométrica, no estadística.

    Devuelve por día: mediodía observado, tránsito calculado y desfase en minutos.
    """
    g = generacion[POTENCIA_AC]
    activo = g[g > umbral_kw]
    if len(activo) < 50:
        return pd.DataFrame(columns=["mediodia_observado", "transito_calculado", "desfase_min"])
    dia = pd.Index(activo.index.date, name="fecha")
    bordes = pd.DataFrame({"t": activo.index}, index=dia).groupby("fecha")["t"].agg(["min", "max"])
    conteo = activo.groupby(dia).size()
    bordes = bordes[conteo >= 6]
    medio = bordes["min"] + (bordes["max"] - bordes["min"]) / 2

    # El tránsito solar se calcula para TODOS los días en una sola llamada. La
    # versión día por día hacía una llamada SPA por jornada y dominaba el costo
    # de la suite entera; sobre tres años eran más de mil llamadas.
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    dias = pd.DatetimeIndex(bordes.index).tz_localize("UTC")
    transito = sitio.get_sun_rise_set_transit(dias, method="spa")["transit"]

    out = pd.DataFrame(
        {
            "mediodia_observado": medio.to_numpy(),
            "transito_calculado": transito.to_numpy(),
            "desfase_min": (medio.to_numpy() - transito.to_numpy()) / np.timedelta64(1, "m"),
        },
        index=bordes.index,
    )
    return out


def firma_recorte(
    generacion: pd.DataFrame, meta: MetadatosSitio, umbral_concentracion: float = 2.5
) -> dict:
    """Detecta meseta de potencia: el objetivo está censurado por arriba.

    La primera versión de este detector medía solo "qué fracción de pasos está
    cerca del techo" y **disparó sobre el escenario limpio**: toda planta tiene
    algo de masa cerca de su propio máximo en días despejados. Medir cercanía al
    techo no distingue recorte de simplemente producir mucho.

    Lo que sí distingue es la FORMA de la cola. Sin recorte la densidad decae
    suavemente al acercarse al máximo; con recorte se amontona en una banda
    plana, porque muchas condiciones distintas producen la misma salida. Se mide
    como razón de concentración entre la banda superior y la inmediatamente
    anterior, de igual ancho. Sin recorte la razón es menor que uno.

    `umbral_concentracion` se calibró contra escenarios de magnitud conocida, no
    a ojo: ver el barrido de razón DC/AC.
    """
    p = generacion[POTENCIA_AC]
    diurno = p[p > 0.02 * meta.capacidad_ac_kw]
    if len(diurno) < 500:
        return {"detectado": False, "motivo": "muestra insuficiente"}

    techo = float(diurno.quantile(0.999))
    ancho = 0.02 * techo
    superior = ((diurno >= techo - ancho) & (diurno <= techo * 1.001)).sum()
    anterior = ((diurno >= techo - 2 * ancho) & (diurno < techo - ancho)).sum()
    razon = superior / max(anterior, 1)
    brecha = (meta.capacidad_ac_kw - techo) / meta.capacidad_ac_kw
    detectado = razon > umbral_concentracion
    return {
        "detectado": bool(detectado),
        "techo_estimado_kw": techo,
        "concentracion": float(razon),
        "fraccion_en_meseta": float(superior / len(diurno)),
        "brecha_vs_placa": float(brecha),
        # Solo tiene sentido preguntarlo si hay recorte: sin meseta, el "techo"
        # estimado es simplemente el máximo que dio el clima, no un límite.
        "discrepancia_placa": bool(detectado and brecha > 0.03),
    }


def indice_desempeno_mensual(
    generacion: pd.DataFrame,
    clima: pd.DataFrame,
    meta: MetadatosSitio,
    poa_min: float = 400.0,
    excluir_recorte: bool = True,
) -> pd.Series:
    """Potencia medida sobre potencia esperada por irradiancia, mediana mensual.

    Se filtra a irradiancia alta y, por defecto, se excluyen los pasos cercanos
    al techo del inversor: **si no se excluye el recorte, el índice baja cuando
    hay más sol y el ensuciamiento se lee al revés.** Esa interacción es el
    motivo por el que las fallas de la capa verdad se inyectan dentro de la
    cadena física y no sobre la salida.
    """
    from .planta import ParametrosPlanta, simular_generacion

    referencia = simular_generacion(
        meta, clima, ParametrosPlanta(suciedad_base=0.0), detalle=True
    )
    j = pd.DataFrame(
        {
            "medida": generacion[POTENCIA_AC],
            "esperada": referencia[POTENCIA_AC],
            "poa": referencia["poa_wm2"],
            "recorte": referencia["recortando"],
        }
    ).dropna()
    m = j["poa"] > poa_min
    if excluir_recorte:
        m &= ~j["recorte"] & (j["medida"] < 0.97 * meta.capacidad_ac_kw)
    j = j[m]
    razon = j["medida"] / j["esperada"].replace(0, np.nan)
    # tz_localize(None) antes de to_period: convertir a período descarta la
    # zona horaria de todos modos, y hacerlo explícito evita el aviso de
    # pandas en cada llamada.
    mes = razon.index.tz_convert("UTC").tz_localize(None).to_period("M")
    return razon.groupby(mes).median().dropna()


def tendencia_desempeno(
    ide: pd.Series, salto_minimo: float = 0.004, pendiente_minima: float = -0.0015
) -> dict:
    """Pendiente del índice de desempeño, medida POR TRAMOS entre lavados.

    Dos correcciones, ambas forzadas por el control negativo:

    1. Ajustar una sola recta a toda la serie lee un diente de sierra como
       pendiente cero: cada lavado deshace la caída anterior y el ajuste global
       la cancela. Con 0.6 %/mes inyectado y tres lavados, el ajuste global daba
       +0.036 %/mes — habría cerrado el caso diciéndole al cliente que no hay
       ensuciamiento. La pendiente se mide dentro de cada tramo y se promedia.

    2. Detectar reinicios por desviación relativa dispara sobre una serie plana,
       donde la dispersión es ruido de punto flotante. Hace falta un salto
       mínimo ABSOLUTO; por debajo de él no hay lavado, hay redondeo.
    """
    if len(ide) < 6:
        return {
            "detectado": False,
            "motivo": "menos de 6 meses: no es separable de la estacionalidad",
            "meses": len(ide),
        }

    y = ide.to_numpy(dtype=float)
    saltos = np.diff(y)
    reinicios = np.flatnonzero(saltos > salto_minimo) + 1

    bordes = [0, *reinicios.tolist(), len(y)]
    pendientes, pesos = [], []
    for a, b in zip(bordes[:-1], bordes[1:]):
        if b - a >= 3:
            pendientes.append(np.polyfit(np.arange(b - a, dtype=float), y[a:b], 1)[0])
            pesos.append(b - a)
    if not pendientes:
        return {
            "detectado": False,
            "motivo": "ningún tramo entre lavados alcanza 3 meses",
            "meses": len(ide),
            "n_reinicios": int(len(reinicios)),
        }

    pend = float(np.average(pendientes, weights=pesos))
    # GUARDIA CONTRA OSCILACIÓN. Un diente de sierra por lavados tiene pocos
    # reinicios y pendientes de tramo parecidas entre sí. Una serie que sube y
    # baja por otra causa —una geometría mal declarada hace oscilar el índice
    # mes a mes— produce muchos "lavados" y pendientes dispares. Sin esta
    # guardia el detector reportaba -0.69 %/mes de ensuciamiento sobre un
    # escenario donde lo único inyectado era un azimut equivocado.
    max_reinicios = max(1, len(ide) // 4)
    signos_coherentes = (
        len(pendientes) == 1 or float(np.std(pendientes)) < 0.6 * abs(pend) + 1e-9
    )
    oscila = len(reinicios) > max_reinicios or not signos_coherentes
    detectado = (pend < pendiente_minima) and not oscila
    separable = len(ide) >= 24
    return {
        "detectado": bool(detectado),
        "pendiente_por_mes": pend,
        "pendiente_global": float(np.polyfit(np.arange(len(y), dtype=float), y, 1)[0]),
        "n_tramos": len(pendientes),
        "meses": len(ide),
        "n_reinicios": int(len(reinicios)),
        "reinicios": [str(ide.index[i]) for i in reinicios],
        "separable_de_estacionalidad": separable,
        "patron_oscilatorio": bool(oscila),
        "advertencia": (
            "patrón oscilatorio, no monótono: la caída no es ensuciamiento; "
            "revisar primero geometría y construcción de la referencia"
        ) if oscila else None if separable else (
            "menos de 24 meses: la pendiente no es separable del ciclo bimodal; "
            "reportar como no concluyente, no como ausencia de ensuciamiento"
        ),
    }


# --------------------------------------------------------------------------
# Mediciones para el resto del catálogo
# --------------------------------------------------------------------------

def _referencia(clima: pd.DataFrame, meta: MetadatosSitio) -> pd.DataFrame:
    from .planta import ParametrosPlanta, simular_generacion

    return simular_generacion(meta, clima, ParametrosPlanta(suciedad_base=0.0), detalle=True)


def dias_anomalos(
    generacion: pd.DataFrame, clima: pd.DataFrame, meta: MetadatosSitio, umbral: float = 0.5
) -> dict:
    """Días cuya energía cae muy por debajo de lo que el clima permitía.

    Separa día OPERATIVAMENTE anómalo de día difícil de pronosticar: aquí la
    referencia es el clima OBSERVADO, así que un día nublado no sale anómalo.
    Lo que sale es la planta apagada.
    """
    ref = _referencia(clima, meta)
    p = generacion[POTENCIA_AC]
    # Un HUECO no es una PARADA. Sumar tratando NaN como cero hace que un día
    # con datos faltantes se lea como planta apagada, y manda a investigar
    # operación cuando el problema es el historiador. Se separan explícitamente.
    completitud = p.notna().resample("D").mean()
    e_med = p.resample("D").sum(min_count=1)
    e_esp = ref[POTENCIA_AC].resample("D").sum()
    razon = (e_med / e_esp.replace(0, np.nan))
    j = pd.DataFrame({"razon": razon, "completitud": completitud}).dropna()
    incompletos = j[j["completitud"] < 0.9]
    malos = j[(j["completitud"] >= 0.9) & (j["razon"] < umbral)]
    return {
        "detectado": len(malos) > 0,
        "n_dias_anomalos": int(len(malos)),
        "n_dias_incompletos": int(len(incompletos)),
        "fraccion": float(len(malos) / max(len(j), 1)),
        "dias": [str(d.date()) for d in malos.index[:12]],
        "razon_mediana_en_anomalos": float(malos["razon"].median()) if len(malos) else None,
    }


def techo_variable(
    generacion: pd.DataFrame, clima: pd.DataFrame, meta: MetadatosSitio,
    poa_min_diaria: float = 4.5, cv_umbral: float = 0.06,
) -> dict:
    """Dispersión del máximo diario de potencia entre días de alta irradiancia.

    Con techo FIJO (placa) el máximo diario es casi el mismo en todos los días
    despejados. Con limitación del OPERADOR el techo cambia de día a día sin que
    el clima lo explique. El filtro por insolación diaria es lo que hace la
    diferencia: sin él, los días nublados aportan máximos bajos y todo parece
    variable.
    """
    ref = _referencia(clima, meta)
    insol = (ref["poa_wm2"].resample("D").sum() * 5 / 60 / 1000)
    pico = generacion[POTENCIA_AC].resample("D").max()
    # ORDEN OBLIGATORIO: las paradas se diagnostican ANTES que la limitación.
    # Un día con la planta apagada tiene pico cero y dispara este detector; sin
    # excluirlos, una parada de cinco días se lee como limitación del operador.
    razon_dia = (generacion[POTENCIA_AC].resample("D").sum()
                 / ref[POTENCIA_AC].resample("D").sum().replace(0, np.nan))
    j = pd.DataFrame({"pico": pico, "insol": insol, "razon": razon_dia}).dropna()
    j = j[j["razon"] > 0.5]
    claros = j[j["insol"] > poa_min_diaria]
    if len(claros) < 20:
        return {"detectado": False, "motivo": "pocos días de alta irradiancia"}
    # La dispersión se mide alrededor del NIVEL LOCAL, no de la media global.
    # Una degradación lenta —ensuciamiento— arrastra el pico diario hacia abajo
    # mes a mes e infla la dispersión global: el detector reportaba limitación
    # del operador sobre un escenario donde lo único inyectado era suciedad.
    # La limitación es dispersión DÍA A DÍA; la degradación es deriva. Un
    # residuo contra la mediana móvil separa una de la otra.
    nivel = claros["pico"].rolling(31, center=True, min_periods=7).median()
    residuo = claros["pico"] / nivel
    cv = float(residuo.std())
    bajos = claros[residuo < 0.85]
    return {
        "detectado": cv > cv_umbral,
        "cv_pico_diario": cv,
        "n_dias_con_techo_bajo": int(len(bajos)),
        "fraccion_dias_limitados": float(len(bajos) / len(claros)),
    }


def asimetria_manana_tarde(
    generacion: pd.DataFrame, clima: pd.DataFrame, meta: MetadatosSitio
) -> dict:
    """Razón mañana/tarde de la energía medida, relativa a la esperada.

    Una orientación real distinta de la declarada corre energía de un lado al
    otro del mediodía solar. Se normaliza contra la esperada porque la curva ya
    es asimétrica por climatología: en el Aburrá la convección vespertina quita
    tarde, y eso NO es un error de orientación.
    """
    ref = _referencia(clima, meta)
    j = pd.DataFrame({"med": generacion[POTENCIA_AC], "esp": ref[POTENCIA_AC]}).dropna()
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    pos = sitio.get_solarposition(j.index)
    manana = pos["azimuth"].to_numpy() < 180.0
    alto = pos["elevation"].to_numpy() > 10.0
    med, esp = j["med"].to_numpy(), j["esp"].to_numpy()
    r_med = med[manana & alto].sum() / max(med[~manana & alto].sum(), 1e-9)
    r_esp = esp[manana & alto].sum() / max(esp[~manana & alto].sum(), 1e-9)
    desv = r_med / r_esp - 1.0
    return {
        "detectado": abs(desv) > 0.02,
        "razon_manana_tarde_medida": float(r_med),
        "razon_esperada": float(r_esp),
        "desviacion_relativa": float(desv),
    }


def rachas_pegadas(generacion: pd.DataFrame, meta: MetadatosSitio, minimo_pasos: int = 6) -> dict:
    """Huecos y rachas de valor congelado en horas de sol.

    El hueco se ve; el valor pegado pasa por dato. Se buscan rachas de
    diferencia EXACTAMENTE cero mientras la planta debería estar produciendo.
    """
    p = generacion[POTENCIA_AC]
    completo = pd.date_range(p.index.min(), p.index.max(),
                             freq=pd.Timedelta(meta.resolucion_nativa))
    presentes = p.reindex(completo)
    huecos = float(presentes.isna().mean())
    vivo = p[p.notna() & (p > 0.03 * meta.capacidad_ac_kw)]
    if vivo.empty:
        return {"detectado": huecos > 0.001, "fraccion_huecos": huecos}
    # La MESETA DE RECORTE también produce diferencias exactamente cero: el
    # inversor entrega su techo paso tras paso. Sin excluirla, este detector
    # acusa de "valores pegados" a toda planta que recorta — disparó 62 rachas
    # sobre el escenario limpio. El recorte es dato bueno; hay que sacarlo antes.
    techo = float(vivo.quantile(0.999))
    diurno = vivo[vivo < techo * 0.98]
    igual = diurno.diff() == 0
    grupo = (~igual).cumsum()
    largos = igual.groupby(grupo).sum()
    rachas = largos[largos >= minimo_pasos]
    pasos_pegados = int(rachas.sum())

    # Un valor congelado y una consigna del operador producen la MISMA firma de
    # varianza nula. Los separa a qué nivel se congelan: una limitación sostiene
    # el máximo del día (la planta sube hasta el techo y se queda ahí); un sensor
    # congelado se queda donde estaba, normalmente a media rampa. Sin este
    # discriminador, la limitación del operador se diagnostica como dato malo y
    # se descartan días que son producción real.
    en_tope = 0
    if len(rachas):
        maximo_dia = diurno.groupby(diurno.index.date).transform("max")
        nivel = diurno[igual].groupby(grupo).transform("first")
        tope = (diurno[igual] >= 0.97 * maximo_dia[igual]).groupby(grupo).mean()
        en_tope = float(tope.reindex(rachas.index).mean())
    return {
        "detectado": bool(len(rachas) > 0 or huecos > 0.001),
        "fraccion_huecos": huecos,
        "n_rachas_pegadas": int(len(rachas)),
        "fraccion_pasos_pegados": float(pasos_pegados / max(len(diurno), 1)),
        "fraccion_rachas_en_tope_diario": en_tope,
        "diagnostico": (
            "consigna del operador o recorte" if en_tope and en_tope > 0.7
            else "sensor congelado" if len(rachas) else "solo huecos"
        ),
    }


def dias_sospechosos(generacion: pd.DataFrame, meta: MetadatosSitio,
                     minimo_pasos: int = 6) -> set:
    """Días con huecos o con valores congelados: dato de calidad dudosa.

    La etapa de calidad no solo reporta: tiene que ENTREGAR la lista de días a
    excluir. Si no, las etapas siguientes diagnostican sobre dato malo — un
    valor congelado nueve horas deprime la energía del día y se lee como parada
    de planta. El orden de diagnóstico solo sirve si se implementa como filtro.
    """
    p = generacion[POTENCIA_AC]
    # Un hueco no siempre llega como NaN: un export de historiador normalmente
    # OMITE la fila. Buscar solo NaN deja pasar la mitad de los huecos, y los
    # días incompletos se van a la etapa de operación donde se leen como
    # paradas de planta.
    malos = set(p.index[p.isna()].date)
    paso = pd.Timedelta(meta.resolucion_nativa)
    por_dia = p.resample("D").count()
    esperados = int(pd.Timedelta("1D") / paso)
    malos |= set(d.date() for d in por_dia.index[por_dia < 0.98 * esperados])
    vivo = p[p.notna() & (p > 0.03 * meta.capacidad_ac_kw)]
    if vivo.empty:
        return malos
    techo = float(vivo.quantile(0.999))
    diurno = vivo[vivo < techo * 0.98]
    igual = diurno.diff() == 0
    grupo = (~igual).cumsum()
    largos = igual.groupby(grupo).sum()
    maximo_dia = diurno.groupby(diurno.index.date).transform("max")
    for g in largos[largos >= minimo_pasos].index:
        tramo = diurno.index[grupo == g]
        # Una racha que se sostiene en el máximo del día es consigna del
        # operador o recorte: producción REAL limitada, no dato malo. Excluirla
        # aquí borraría justo los días que la etapa de operación necesita ver,
        # y el diagnóstico de limitación se perdería por completo.
        if (diurno[grupo == g] >= 0.97 * maximo_dia[grupo == g]).mean() > 0.7:
            continue
        malos |= set(tramo.date)
    return malos


def salto_de_nivel(ide: pd.Series, umbral: float = 0.08, n_sigmas: float = 5.0) -> dict:
    """Cambio de nivel del índice de desempeño: capacidad distinta de la declarada.

    Un umbral absoluto no basta. Una serie con oscilación estacional fuerte
    —por ejemplo una orientación real distinta de la declarada, que hace variar
    el índice mes a mes— produce diferencias grandes sin que haya escalón, y la
    primera versión de este detector la acusó de ampliación de capacidad. Un
    escalón real se distingue por dos cosas: domina sobre la volatilidad típica
    mes a mes, y el nivel NUEVO PERSISTE en vez de volver.
    """
    if len(ide) < 6:
        return {"detectado": False, "motivo": "serie corta"}
    d = ide.diff().dropna()
    volatilidad = float(np.median(np.abs(d.to_numpy() - np.median(d.to_numpy())))) or 1e-9
    i = int(np.argmax(np.abs(d.to_numpy())))
    salto = float(d.iloc[i])
    antes = float(ide.iloc[: i + 1].median())
    despues = float(ide.iloc[i + 1 :].median())
    persiste = abs(despues - antes) > 0.6 * abs(salto)
    domina = abs(salto) > n_sigmas * volatilidad
    return {
        "detectado": bool(abs(salto) > umbral and domina and persiste),
        "salto": salto,
        "mes_del_salto": str(d.index[i]),
        "nivel_antes": antes,
        "nivel_despues": despues,
        "salto_sobre_volatilidad": float(abs(salto) / volatilidad),
        "persiste": bool(persiste),
    }


def razon_por_elevacion(
    generacion: pd.DataFrame, clima: pd.DataFrame, meta: MetadatosSitio,
    bandas: tuple[float, ...] = (0, 10, 20, 35, 90),
) -> dict:
    """Razón medida/esperada por banda de elevación solar.

    El sombreado de horizonte golpea SOLO a sol bajo. Si la razón cae en la
    banda inferior y se mantiene arriba, el problema es geométrico y no del
    modelo; si cae parejo en todas, es otra cosa.
    """
    ref = _referencia(clima, meta)
    j = pd.DataFrame({"med": generacion[POTENCIA_AC], "esp": ref[POTENCIA_AC]}).dropna()
    sitio = Location(meta.latitud, meta.longitud, meta.zona_horaria, meta.altitud_m)
    elev = sitio.get_solarposition(j.index)["elevation"].to_numpy()
    med, esp = j["med"].to_numpy(), j["esp"].to_numpy()
    razones = {}
    for a, b in zip(bandas[:-1], bandas[1:]):
        m = (elev >= a) & (elev < b) & (esp > 0.01 * meta.capacidad_ac_kw)
        if m.sum() > 100:
            razones[f"{int(a)}-{int(b)}°"] = float(med[m].sum() / max(esp[m].sum(), 1e-9))
    if len(razones) < 2:
        return {"detectado": False, "razones": razones}
    # La firma NO está necesariamente en la banda más baja. Si la línea base ya
    # obstruye los primeros grados —y en cubierta urbana del Aburrá sí—, allí no
    # hay pérdida ADICIONAL y la razón vuelve a ~1. La obstrucción extra aparece
    # en la banda inmediatamente superior. Buscar solo en la banda inferior deja
    # pasar la falla: el perfil inyectado da 0.96 en 0-10° y 0.70 en 10-20°.
    peor = min(razones, key=razones.get)
    alta = list(razones)[-1]
    contraste = float(razones[alta] - razones[peor])
    return {
        "detectado": bool(peor != alta and contraste > 0.05),
        "razones": razones,
        "banda_mas_afectada": peor,
        "contraste_bajo_vs_alto": contraste,
    }


def techo_alcanzable(
    fuente, meta: MetadatosSitio, desde, hasta,
    horizonte: tuple[float, float] = (24.0, 48.0),
    umbral_sesgo: float = 0.40, umbral_importado: float = 3.0,
) -> dict:
    """Primer experimento obligatorio de la Fase 7, medido.

    Alimenta el mismo modelo con clima PRONOSTICADO y con clima OBSERVADO. La
    diferencia es el error importado del proveedor meteorológico; lo que queda
    es el techo alcanzable, es decir cuánta mejora hay realmente en venta.

    El umbral de sesgo es el de la matriz: por encima del 40 % del MAE el error
    es sistemático y se ataca con post-proceso del NWP. Por debajo domina la
    varianza, y ahí post-procesar no sirve: el mecanismo grande es la
    temporización, cuyo sesgo medio es cero.

    Es caro —exige generar el archivo de pronóstico completo— y por eso no va
    en el CI rápido.
    """
    from .contrato import COLS_CLIMA, HORIZONTE_H, INSTANTE
    from .planta import simular_generacion

    verdad = (fuente.verdad()[POTENCIA_AC]
              .resample("1h", label="left", closed="left").mean().rename("real"))

    def _error(archivo):
        s = archivo[(archivo[HORIZONTE_H] > horizonte[0])
                    & (archivo[HORIZONTE_H] <= horizonte[1])].reset_index().set_index(INSTANTE)
        s = s[~s.index.duplicated()].sort_index()[COLS_CLIMA]
        c = s.copy(); c.index = c.index + pd.Timedelta(minutes=30)   # geometría a mitad de hora
        p = simular_generacion(meta, c)
        p.index = p.index - pd.Timedelta(minutes=30)
        j = p.join(verdad, how="inner").dropna()
        j = j[j["real"] > 0.01 * meta.capacidad_ac_kw]
        e = j[POTENCIA_AC] - j["real"]
        return float(e.abs().mean()), float(e.mean())

    mae_p, sesgo_p = _error(fuente.clima_pronosticado(desde, hasta))
    mae_o, _ = _error(fuente.clima_como_si_fuera_perfecto(desde, hasta))
    razon_sesgo = abs(sesgo_p) / max(mae_p, 1e-9)
    importado = mae_p / max(mae_o, 1e-9)
    return {
        "mae_con_pronostico_kw": mae_p,
        "mae_con_observado_kw": mae_o,
        "sesgo_con_pronostico_kw": sesgo_p,
        "sesgo_sobre_mae": razon_sesgo,
        "razon_importado": importado,
        "fraccion_importada": 1.0 - mae_o / max(mae_p, 1e-9),
        "sesgo_importado": bool(razon_sesgo > umbral_sesgo and importado > umbral_importado),
    }
