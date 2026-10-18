"""Pruebas del banco sintético. Corren en integración continua.

Dos familias:

  * CONTRATO — la fuente cumple el esquema, el corte as-of funciona, el
    pronóstico perfecto reproduce la verdad. Esta última es el control que
    atrapó un bug de unidades de tiempo que ningún test de forma habría visto.

  * DIAGNÓSTICO (3.4 / 3.5) — el agente de referencia identifica cada falla
    inyectada con el detector correcto, y no inventa nada sobre el escenario
    limpio.

La ventana es corta a propósito: la suite tiene que correr en CI. Las fallas
que necesitan historia larga (suciedad: 24 meses) se marcan `lento` y corren
aparte.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import numpy as np
import pandas as pd
import pytest

from banco.agente import diagnosticar
from banco.calificacion import calificar
from banco.contrato import (
    HORIZONTE_H,
    POTENCIA_AC,
    validar_clima,
    validar_generacion,
    validar_pronostico,
)
from banco.fallas import (
    AmpliacionCapacidad,
    DesfaseHorario,
    HuecosYPegados,
    LimitacionOperador,
    OrientacionDeclarada,
    ParadasMantenimiento,
    RecorteInversor,
    SombreadoHorizonte,
)
from banco.fuente import FuenteSintetica
from banco.sitios import MEDELLIN_REF, SITIOS

INI, FIN = dt.date(2023, 1, 1), dt.date(2024, 1, 1)
U, V = pd.Timestamp(INI, tz="UTC"), pd.Timestamp(FIN, tz="UTC")
TODO = pd.Timestamp("2026-01-01", tz="UTC")


@pytest.fixture(scope="module")
def limpia():
    return FuenteSintetica(MEDELLIN_REF, INI, FIN)


# ----------------------------------------------------------------- contrato

def test_esquemas(limpia):
    validar_generacion(limpia.generacion(U, V, TODO), MEDELLIN_REF)
    validar_clima(limpia.clima_observado(U, V))


def test_as_of_respeta_el_rezago(limpia):
    as_of = pd.Timestamp("2023-06-15 12:00", tz="UTC")
    g = limpia.generacion(U, V, as_of)
    assert g.index.max() < as_of - MEDELLIN_REF.rezago_publicacion
    assert g.index.max() > as_of - MEDELLIN_REF.rezago_publicacion - pd.Timedelta("15min")


def test_energia_en_rango_fisico(limpia):
    e = limpia.verdad()[POTENCIA_AC].sum() * 5 / 60
    rendimiento = e / MEDELLIN_REF.capacidad_dc_kwp
    assert 1100 < rendimiento < 1600, f"yield {rendimiento:.0f} kWh/kWp fuera de rango"


def test_pronostico_perfecto_reproduce_la_verdad(limpia):
    """Control que atrapó un desfase silencioso de mil veces en la conversión
    de tiempo cuando pandas cambió su resolución interna."""
    a, b = pd.Timestamp("2023-03-01", tz="UTC"), pd.Timestamp("2023-03-15", tz="UTC")
    perf = limpia.clima_como_si_fuera_perfecto(a, b)
    validar_pronostico(perf)
    obs = limpia.clima_observado(a, b).resample("1h", label="left", closed="left").mean()
    s = perf[(perf[HORIZONTE_H] > 1) & (perf[HORIZONTE_H] <= 24)].reset_index().set_index("instante")
    s = s[~s.index.duplicated()].sort_index()
    j = s.join(obs[["ghi_wm2"]].rename(columns={"ghi_wm2": "obs"}), how="inner").dropna()
    dia = j["obs"] > 20
    assert abs((j["ghi_wm2"] - j["obs"])[dia].mean()) < 5.0


def test_pronostico_nunca_precede_a_su_emision(limpia):
    a, b = pd.Timestamp("2023-03-01", tz="UTC"), pd.Timestamp("2023-03-08", tz="UTC")
    validar_pronostico(limpia.clima_pronosticado(a, b))


def test_capas_no_se_mezclan():
    """Una falla de la capa MEDICIÓN no debe tocar la verdad física."""
    base = FuenteSintetica(MEDELLIN_REF, INI, dt.date(2023, 4, 1))
    con = FuenteSintetica(MEDELLIN_REF, INI, dt.date(2023, 4, 1), fallas=(HuecosYPegados(),))
    assert np.isclose(
        base.verdad()[POTENCIA_AC].sum(), con.verdad()[POTENCIA_AC].sum()
    )
    assert con.generacion(U, V, TODO)[POTENCIA_AC].isna().sum() == 0  # dropna en medición
    assert len(con.generacion(U, V, TODO)) < len(base.generacion(U, V, TODO))


# -------------------------------------------------------- diagnóstico 3.4/3.5

ESCENARIOS = [
    ("desfase_utc", MEDELLIN_REF, (DesfaseHorario(horas=-5.0),)),
    ("paradas", MEDELLIN_REF, (ParadasMantenimiento(
        ventanas=((dt.datetime(2023, 5, 3), dt.datetime(2023, 5, 8)),)),)),
    ("limitacion", MEDELLIN_REF, (LimitacionOperador(),)),
    ("recorte", SITIOS["med-ref-560-dcac140"], (RecorteInversor(),)),
    ("orientacion", MEDELLIN_REF, (OrientacionDeclarada(azimut_real=215.0),)),
    ("sombreado", MEDELLIN_REF, (SombreadoHorizonte(),)),
    ("huecos", MEDELLIN_REF, (HuecosYPegados(),)),
]


def _calificar(nombre, meta, fallas):
    f = FuenteSintetica(meta, INI, FIN, fallas=fallas)
    g = f.generacion(U, V, TODO)
    return calificar(nombre, diagnosticar(g, f.clima_observado(U, V), meta), f.manifiesto())


def test_control_negativo_35():
    """La única salida aprobatoria sobre datos limpios es la lista vacía."""
    c = _calificar("limpio", MEDELLIN_REF, ())
    assert c.aprueba, c.motivo()
    assert not c.encontradas, f"inventó {c.encontradas}"


@pytest.mark.parametrize("nombre,meta,fallas", ESCENARIOS, ids=[e[0] for e in ESCENARIOS])
def test_acierto_diagnostico_34(nombre, meta, fallas):
    c = _calificar(nombre, meta, fallas)
    assert c.aprueba, c.motivo()


@pytest.mark.lento
def test_suciedad_necesita_24_meses():
    """Con 12 meses el detector mide bien la pendiente pero NO puede separarla
    de la estacionalidad bimodal. La respuesta correcta es 'no concluyente',
    no 'no hay ensuciamiento'."""
    from banco.fallas import DerivaSuciedad
    from banco.mediciones import indice_desempeno_mensual, tendencia_desempeno

    f = FuenteSintetica(
        MEDELLIN_REF, dt.date(2023, 1, 1), dt.date(2025, 1, 1),
        fallas=(DerivaSuciedad(tasa_mensual=0.006,
                               lavados=(dt.date(2023, 7, 1), dt.date(2024, 1, 15))),),
    )
    a, b = pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")
    ide = indice_desempeno_mensual(f.verdad()[[POTENCIA_AC]], f.clima_observado(a, b), MEDELLIN_REF)
    t24 = tendencia_desempeno(ide)
    assert t24["detectado"] and t24["separable_de_estacionalidad"]
    assert abs(t24["pendiente_por_mes"] + 0.006) < 0.0015
    t12 = tendencia_desempeno(ide.iloc[:12])
    assert not t12["separable_de_estacionalidad"]
    assert t12["advertencia"]


@pytest.mark.lento
def test_sesgo_meteorologico_solo_se_ve_con_clima_observado():
    """El error importado del proveedor es alto SIEMPRE (~90 %); lo que el
    sesgo inyectado cambia es que ese error se vuelve SISTEMÁTICO.

    La distinción decide la recomendación: por encima del 40 % del MAE se
    post-procesa el NWP; por debajo domina la temporización, cuyo sesgo medio
    es cero y a la que post-procesar no le hace nada.
    """
    from banco.fallas import SesgoMeteorologico
    from banco.mediciones import techo_alcanzable

    a = dt.date(2023, 1, 1); b = dt.date(2023, 5, 1)
    d = pd.Timestamp("2023-01-10", tz="UTC"); h = pd.Timestamp("2023-04-20", tz="UTC")

    base = techo_alcanzable(FuenteSintetica(MEDELLIN_REF, a, b), MEDELLIN_REF, d, h)
    con = techo_alcanzable(
        FuenteSintetica(MEDELLIN_REF, a, b, fallas=(SesgoMeteorologico(),)), MEDELLIN_REF, d, h
    )
    # En ambos casi todo el error viene del meteorológico...
    assert base["fraccion_importada"] > 0.8 and con["fraccion_importada"] > 0.8
    # ...pero solo con la falla inyectada es sistemático.
    assert not base["sesgo_importado"]
    assert con["sesgo_importado"] and con["sesgo_sobre_mae"] > 0.40


def test_particion_es_temporal_y_con_separacion():
    """Bloques contiguos en el tiempo, sin solape y con días de separación.

    Partir al azar filtraría información: el día siguiente comparte régimen
    meteorológico con el anterior, así que un día de prueba rodeado de días de
    entrenamiento es casi un día visto.
    """
    from banco.modelo import particion_por_bloques

    idx = pd.date_range("2023-01-01", periods=24 * 300, freq="1h", tz="UTC", name="instante")
    conj = pd.DataFrame({"real": np.arange(len(idx), dtype=float)}, index=idx)
    tr, va, te = particion_por_bloques(conj, separacion_dias=7)

    d_tr, d_va, d_te = (set(x.index.date) for x in (tr, va, te))
    assert not (d_tr & d_va) and not (d_va & d_te) and not (d_tr & d_te)
    assert max(d_tr) < min(d_va) < max(d_va) < min(d_te)   # contiguos y en orden
    assert (min(d_va) - max(d_tr)).days > 7                # separación efectiva
    assert (min(d_te) - max(d_va)).days > 7


def test_intercambio_de_fuente_da_el_mismo_veredicto(tmp_path):
    """La afirmación central de la Fase 3.6, probada.

    El mismo agente, sin una línea distinta, leyendo de una carpeta de CSV en
    hora LOCAL y sin zona horaria, debe llegar al mismo diagnóstico que leyendo
    de la planta sintética. Un Protocol con un solo implementador no demuestra
    que la fuente sea intercambiable; esto sí.
    """
    from banco.agente import diagnosticar
    from banco.fuente_csv import FuenteCSV, exportar_csv

    a, b = dt.date(2023, 1, 1), dt.date(2023, 7, 1)
    u, v = pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")
    sin = FuenteSintetica(MEDELLIN_REF, a, b, fallas=(DesfaseHorario(horas=-5.0),))
    exportar_csv(sin, tmp_path / "export", u, v)
    csv = FuenteCSV(tmp_path / "export")

    # La ida y vuelta por hora local naive es donde vive la falla de 5 horas.
    assert csv.metadatos_sitio() == sin.metadatos_sitio()
    assert str(csv.generacion(u, v, TODO).index.tz) == "UTC"
    pd.testing.assert_frame_equal(
        csv.generacion(u, v, TODO), sin.generacion(u, v, TODO), check_freq=False
    )

    h_sin = sorted(h.falla for h in diagnosticar(
        sin.generacion(u, v, TODO), sin.clima_observado(u, v), MEDELLIN_REF))
    h_csv = sorted(h.falla for h in diagnosticar(
        csv.generacion(u, v, TODO), csv.clima_observado(u, v), csv.metadatos_sitio()))
    assert h_sin == h_csv == ["desfase_horario"]


def test_criterios_de_muerte_detienen_cuando_deben():
    """Los criterios se pactan antes y se evalúan con números.

    Un criterio que se decide después de ver los datos no es un criterio: es
    una racionalización. Esta prueba fija los umbrales en el repositorio.
    """
    from banco.criterios import (
        Estado, m1_historia_minima, m3_fase1_cerrada, m5_margen_disponible,
        m6_calidad_del_dato, m8_punto_ciego, m9_supera_lineas_base,
    )

    assert m1_historia_minima(24, 5).estado is Estado.SIGUE
    assert m1_historia_minima(8, 15).estado is Estado.DETENTE          # sin historia
    assert m3_fase1_cerrada(True, True, False).estado is Estado.DETENTE  # sin penalidad
    assert m5_margen_disponible(50.0, 47.0).estado is Estado.DETENTE   # 6 % de margen
    assert m5_margen_disponible(47.7, 6.1).estado is Estado.SIGUE
    # Sin bitácora, un 22 % de días inservibles no es diagnosticable.
    assert m6_calidad_del_dato(0.22, registro_eventos=False).estado is Estado.DETENTE
    assert m6_calidad_del_dato(0.22, registro_eventos=True).estado is Estado.REPLANTEA
    # El silencio del agente sobre un punto ciego conocido NO es un resultado.
    assert m8_punto_ciego(0, "perdida_desalineada").estado is Estado.REPLANTEA
    assert m8_punto_ciego(2, "error_importado").estado is Estado.SIGUE
    # No superar la vara es DETENTE, aunque la diferencia tenga el signo bueno.
    assert m9_supera_lineas_base(-0.4, 1.9).estado is Estado.DETENTE
    assert m9_supera_lineas_base(-5.06, 1.99).estado is Estado.SIGUE


@pytest.fixture(scope="module")
def artefactos_min(tmp_path_factory):
    """Artefactos sobre una ventana corta, suficientes para verificar forma."""
    from banco.artefactos import generar
    from banco.lineas_base import ModeloFisico, PersistenciaCieloDespejado
    from banco.backtest import correr
    from banco.mediciones import indice_desempeno_mensual
    from banco.modelo import construir_conjunto

    a, b = dt.date(2023, 1, 1), dt.date(2023, 4, 1)
    f = FuenteSintetica(MEDELLIN_REF, a, b)
    conj = construir_conjunto(f, MEDELLIN_REF, dt.date(2023, 1, 5), dt.date(2023, 3, 25))
    pred = correr(f, MEDELLIN_REF,
                  {m.nombre: m for m in (ModeloFisico(), PersistenciaCieloDespejado())},
                  dt.date(2023, 1, 5), dt.date(2023, 3, 25))
    u, v = pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")
    ide = indice_desempeno_mensual(f.verdad()[[POTENCIA_AC]], f.clima_observado(u, v), MEDELLIN_REF)
    carpeta = tmp_path_factory.mktemp("art")
    generar(carpeta, conj, pred, ide, MEDELLIN_REF, mae_techo=6.0, vara=2.0)
    return carpeta, pred


def test_artefactos_no_salen_vacios(artefactos_min):
    """Una figura vacía pesa poco y un parquet truncado se lee sin error.

    Sin esta prueba, un cambio en el pipeline puede dejar al Colab mostrando un
    lienzo en blanco y la suite no se entera. Se verifica contenido, no
    existencia: tamaño mínimo de PNG, filas y columnas del parquet, y que el
    resumen traiga las claves que la lectura de negocio necesita.
    """
    import json

    carpeta, pred = artefactos_min
    for png in ("fig_pronostico.png", "fig_residuo.png", "fig_desempeno.png"):
        p = carpeta / png
        assert p.exists(), f"falta {png}"
        # Un PNG en blanco de este tamaño pesa ~10 KB; con datos, bastante más.
        assert p.stat().st_size > 20_000, f"{png} pesa {p.stat().st_size} B: probablemente vacía"

    conj = pd.read_parquet(carpeta / "conjunto.parquet")
    pr = pd.read_parquet(carpeta / "predicciones.parquet")
    assert len(conj) > 24 * 50 and len(pr) > 24 * 50
    assert {"real", "modelo_fisico"} <= set(pr.columns)
    assert str(pr.index.tz) == "UTC"
    pd.testing.assert_series_equal(pr["real"], pred["real"], check_freq=False)

    res = json.loads((carpeta / "resumen.json").read_text("utf-8"))
    for k in ("mae_modelo_kw", "mae_mejor_linea_base_kw", "vara_kw", "supera_la_vara",
              "mae_techo_alcanzable_kw", "fraccion_error_importada_del_meteorologico",
              "dias_evaluados", "advertencia"):
        assert k in res, f"el resumen no trae {k}"
    # Rangos físicos: un resumen con números absurdos pasa el chequeo de claves.
    assert 0 < res["mae_modelo_kw"] < MEDELLIN_REF.capacidad_ac_kw
    assert 0 <= res["fraccion_error_importada_del_meteorologico"] <= 1
    assert res["dias_evaluados"] > 50
    # La advertencia es parte del artefacto, no una nota al pie que se pierde.
    assert "Fase 1" in res["advertencia"] and "SINTÉTICA" in res["advertencia"]


def test_auditoria_de_licencias_sin_copyleft():
    """Las licencias se verifican leyendo lo instalado, no una página web.

    La primera versión del escáner reportó MIT para numpy, porque recorría
    subcarpetas y encontraba la licencia de un componente empotrado (el
    generador Mersenne Twister) antes que la del paquete. El metadato
    normativo `License-Expression` dice BSD-3-Clause AND 0BSD AND MIT AND Zlib
    AND CC0-1.0. Esta prueba fija que el método correcto siga siendo el usado.
    """
    from banco.licencias import PERMISIVAS, auditar

    numpy = auditar("numpy")
    assert numpy["metodo"] == "normativo"
    assert numpy["licencia"].startswith("BSD-3-Clause")

    for pkg in ("pvlib", "pandas", "scipy", "scikit-learn", "pyarrow"):
        a = auditar(pkg)
        assert a["licencia"] != "no instalado", f"{pkg} no instalado"
        assert a["metodo"] != "OLFATEO — verificar a mano", f"{pkg} sin licencia verificable"
        assert a["licencia"].split(" (")[0] in PERMISIVAS, f"{pkg}: {a['licencia']}"


def test_postproceso_preserva_consistencia_de_componentes():
    """Tocar la global obliga a recomponer directa y difusa.

    Cambiar GHI y dejar DNI y DHI como estaban deja el archivo inconsistente:
    la transposición al plano del arreglo los usa por separado y produciría una
    irradiancia que no corresponde a ninguna condición física.
    """
    from banco.contrato import DHI, DNI, GHI
    from banco.postproceso import EnsambleMeteorologico, MezclaFuentes

    a, b = dt.date(2023, 1, 1), dt.date(2023, 2, 1)
    f = FuenteSintetica(MEDELLIN_REF, a, b)
    A = f.clima_pronosticado(pd.Timestamp("2023-01-05", tz="UTC"),
                             pd.Timestamp("2023-01-20", tz="UTC"))
    B = A.copy()
    B[GHI] = B[GHI] * 0.8

    for salida in (MezclaFuentes().aplicar(A, B, MEDELLIN_REF),
                   EnsambleMeteorologico().aplicar([A, B], MEDELLIN_REF)):
        assert len(salida) == len(A)
        # La global queda entre las dos entradas, y las componentes se rehicieron.
        assert (salida[GHI] <= A[GHI] + 1e-6).all() and (salida[GHI] >= B[GHI] - 1e-6).all()
        assert not salida[DNI].equals(A[DNI]), "DNI no se recompuso"
        assert not salida[DHI].equals(A[DHI]), "DHI no se recompuso"
        assert (salida[[GHI, DNI, DHI]] >= 0).all().all()

    with pytest.raises(ValueError):
        EnsambleMeteorologico().aplicar([A], MEDELLIN_REF)


def test_criterio_de_rol_regulatorio():
    """Un AGPE no paga desviaciones horarias: se liquida por período.

    Verificado contra regulación colombiana en octubre de 2026. Es el hallazgo
    que puede detener el proyecto para la planta de referencia, así que queda
    fijado aquí y no solo en un documento.
    """
    from banco.criterios import Estado, m11_rol_expuesto_al_error

    assert m11_rol_expuesto_al_error("agpe").estado is Estado.REPLANTEA
    assert m11_rol_expuesto_al_error("generador_no_despachado").estado is Estado.SIGUE
    assert m11_rol_expuesto_al_error("usuario_no_regulado").estado is Estado.SIGUE
    assert m11_rol_expuesto_al_error("generador_despachado").estado is Estado.SIGUE


def test_cuaderno_colab_es_ejecutable():
    """El .ipynb exige que cada línea de `source` termine en salto de línea.

    Sin eso el archivo valida igual y hasta se ve bien en pantalla, pero al
    ejecutar, las líneas quedan pegadas: `import afrom b import c` →
    SyntaxError. Pasó en producción con este cuaderno. Aquí se compila el
    código de cada celda, que es la única comprobación que lo habría atrapado.
    """
    import ast
    import json

    nb = json.loads(
        (pathlib.Path(__file__).parent.parent / "colab" / "pronostico_solar.ipynb")
        .read_text("utf-8")
    )
    assert nb["cells"], "el cuaderno no tiene celdas"
    for i, c in enumerate(nb["cells"]):
        src = c["source"]
        assert isinstance(src, list) and src, f"celda {i} sin contenido"
        for j, linea in enumerate(src[:-1]):
            assert linea.endswith("\n"), f"celda {i}, línea {j} sin salto de línea"
        if c["cell_type"] == "code":
            ast.parse("".join(src))   # SyntaxError si las líneas quedaron pegadas
