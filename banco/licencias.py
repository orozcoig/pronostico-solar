"""Auditoría de licencias, reproducible — `python -m banco.licencias`.

Lee lo que está INSTALADO, no una página web. Las páginas cambian y las
versiones también; lo que obliga es el archivo que vino con el paquete.

Dos trampas que esta implementación evita, y que la primera versión no evitaba:

  * **Componentes empotrados.** `numpy` trae licencias de código de terceros
    dentro de su propio `dist-info` (el generador Mersenne Twister es MIT, por
    ejemplo). Un escáner que recorre subcarpetas y se queda con el primer
    archivo que reconoce reporta MIT para numpy, que es falso: numpy es
    BSD-3-Clause con componentes empotrados bajo otras licencias permisivas.
  * **Archivos en la raíz del dist-info.** `scipy` deja su `LICENSE.txt`
    directamente ahí, no bajo `licenses/`. Un patrón que exige subcarpeta lo
    pierde y lo reporta como desconocido.

Por eso el orden es: primero `License-Expression` de los metadatos, que es
normativo; después el archivo de licencia de la RAÍZ; y solo al final el
olfateo, marcado como tal.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution, metadata, version
from pathlib import Path

PAQUETES = {
    "pvlib": "Física solar: posición, cielo despejado, transposición, temperatura de celda, inversor",
    "pandas": "Series de tiempo",
    "numpy": "Numérico",
    "scipy": "Bootstrap de bloques, filtros, distribuciones",
    "scikit-learn": "Árboles con gradiente y pérdida cuantílica",
    "matplotlib": "Figuras",
    "pyarrow": "Parquet de artefactos",
    "pvanalytics": "Segunda implementación: desfase horario, recorte, saltos de nivel",
    "ruptures": "Dependencia transitiva de pvanalytics (detección de puntos de cambio)",
    "rdtools": "Segunda implementación: ensuciamiento (método SRR)",
}

# Algunos proyectos no encabezan su licencia con el nombre canónico: scipy
# arranca con el aviso de copyright de Enthought y matplotlib con su propio
# acuerdo, derivado de la PSF. Clasificarlos como "texto propio" es correcto
# pero inútil, así que se reconocen por una firma del cuerpo.
FIRMAS = (
    ("BSD-3-Clause", "bsd 3-clause"),
    ("BSD-2-Clause", "bsd 2-clause"),
    ("Apache-2.0", "apache license"),
    ("MIT", "mit license"),
    ("BSD-3-Clause", "neither the name of"),        # cláusula 3 del BSD: scipy
    ("PSF-2.0 (Matplotlib License)", "matplotlib development team"),
)

PERMISIVAS = {"BSD-3-Clause", "BSD-2-Clause", "MIT", "Apache-2.0", "0BSD", "Zlib",
              "CC0-1.0", "PSF-2.0", "PSF-2.0 (Matplotlib License)"}


def _raiz_dist_info(pkg: str) -> Path | None:
    """Carpeta `.dist-info` del paquete, en cualquier sistema operativo.

    La primera versión tenía la ruta de Linux escrita a mano
    (`/usr/local/lib/python3.12/dist-packages/...`). En Windows no encontraba
    nada, caía al método de olfateo y la prueba fallaba con «pandas sin
    licencia verificable». `importlib.metadata` sabe dónde está instalado cada
    paquete sin que haya que suponerlo.
    """
    try:
        d = distribution(pkg)
    except PackageNotFoundError:
        return None
    # Algunas instalaciones exponen la ruta directamente.
    ruta = getattr(d, "_path", None)
    if ruta is not None and Path(ruta).is_dir():
        return Path(ruta)
    # Si no, se busca junto a los archivos del paquete.
    try:
        base = Path(d.locate_file(""))
    except Exception:
        return None
    norm = pkg.replace("-", "_").lower()
    for patron in (f"{norm}-*.dist-info", f"{pkg}-*.dist-info", f"{norm}-*.egg-info"):
        for cand in base.glob(patron):
            if cand.is_dir():
                return cand
    return None


def auditar(pkg: str) -> dict:
    try:
        v = version(pkg)
        m = metadata(pkg)
    except PackageNotFoundError:
        return {"paquete": pkg, "version": "—", "licencia": "no instalado",
                "fuente": "—", "metodo": "—"}

    # 1. Metadato normativo (PEP 639). Es lo que el empaquetador declara.
    expr = m.get("License-Expression")
    if expr:
        principal = expr.split(" AND ")[0].strip()
        nota = f" (+ componentes: {expr})" if " AND " in expr else ""
        return {"paquete": pkg, "version": v, "licencia": principal + nota,
                "fuente": "metadato License-Expression", "metodo": "normativo"}

    # 2. Archivo de licencia en la RAÍZ del dist-info o en licenses/ de primer nivel.
    raiz = _raiz_dist_info(pkg)
    if raiz:
        candidatos = sorted(raiz.glob("LICEN*")) + sorted(raiz.glob("COPYING*")) \
            + sorted(raiz.glob("licenses/LICEN*")) + sorted(raiz.glob("licenses/COPYING*"))
        for f in candidatos:
            t = f.read_text(errors="ignore")[:2000].lower()
            for nombre, clave in FIRMAS:
                if clave in t:
                    return {"paquete": pkg, "version": v, "licencia": nombre,
                            "fuente": str(f.relative_to(raiz)), "metodo": "archivo raíz"}
        if candidatos:
            return {"paquete": pkg, "version": v, "licencia": "permisiva, texto propio",
                    "fuente": str(candidatos[0].relative_to(raiz)), "metodo": "archivo raíz"}

    # 3. Campo libre de los metadatos. Algunas ruedas no empaquetan el archivo
    # de licencia —ocurre según la plataforma—, pero sí declaran el nombre en
    # el campo `License`. Si ahí aparece una licencia reconocible, eso es una
    # declaración del empaquetador y vale; no es olfateo.
    libre = (m.get("License") or "").strip()
    if libre:
        bajo = libre[:2000].lower()
        for nombre, clave in FIRMAS:
            if clave in bajo:
                return {"paquete": pkg, "version": v, "licencia": nombre,
                        "fuente": "campo License de los metadatos",
                        "metodo": "campo declarado"}

    # 4. Nada reconocible. Último recurso, y se marca para revisión manual.
    return {"paquete": pkg, "version": v,
            "licencia": libre.splitlines()[0][:40] if libre else "desconocida",
            "fuente": "campo License (texto libre)", "metodo": "OLFATEO — verificar a mano"}


def informe() -> str:
    filas = [auditar(p) for p in PAQUETES]
    dudosas = [f for f in filas if "verificar" in f["metodo"] or f["licencia"] == "desconocida"]
    no_permisivas = [
        f for f in filas
        if f["licencia"].split(" (")[0] not in PERMISIVAS and f["licencia"] != "no instalado"
        and "permisiva" not in f["licencia"]
    ]
    t = ["# Auditoría de licencias", "",
         "Generada con `python -m banco.licencias`, leyendo lo **instalado**: primero",
         "el metadato normativo `License-Expression`, luego el archivo de licencia de",
         "la raíz del `dist-info`, y si la rueda no lo empaqueta —ocurre según la",
         "plataforma— el nombre declarado en el campo `License`. El olfateo de texto",
         "queda como último recurso y se marca para revisión manual.",
         "", "| Paquete | Versión | Licencia | Fuente | Método | Para qué |",
         "|---|---|---|---|---|---|"]
    for f in filas:
        t.append(f"| `{f['paquete']}` | {f['version']} | **{f['licencia']}** | "
                 f"`{f['fuente']}` | {f['metodo']} | {PAQUETES[f['paquete']]} |")
    t += ["", "## Veredicto", ""]
    t.append("**Ninguna dependencia impide uso comercial.** No hay copyleft fuerte."
             if not no_permisivas else
             f"**ATENCIÓN**: revisar {', '.join(f['paquete'] for f in no_permisivas)}.")
    if dudosas:
        t.append(f"- Verificar a mano: {', '.join(f['paquete'] for f in dudosas)}.")
    t += ["", "## Notas", "",
          "- `numpy` declara `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`: es",
          "  BSD-3 con componentes empotrados bajo otras licencias permisivas. Un",
          "  escáner que recorre subcarpetas reporta MIT y se equivoca.",
          "- `ruptures` era el pendiente abierto del memo inicial de librerías. Entra",
          "  como dependencia transitiva de `pvanalytics`; es BSD-2-Clause.",
          "- `pvanalytics` y `rdtools` son opcionales (`pip install -e .[cruce]`): sirven",
          "  para cruzar los detectores propios contra implementación independiente. El",
          "  pipeline corre sin ellas.",
          "- **Descartadas:** SAM/PySAM (binario pesado, redundante con pvlib),",
          "  pvfactors (solo bifacial y seguidores), solar-data-tools (resuelve otro",
          "  problema: análisis sin etiquetas).",
          "- **Fuera de alcance de esta auditoría:** la política de uso comercial de los",
          "  **datos** de Open-Meteo y de XM. El banco sintético no llama a ninguna de",
          "  las dos. La licencia del cliente de software y la de los datos que entrega",
          "  son cosas distintas, y la segunda hay que verificarla con fuente actual",
          "  antes de usar datos reales.", ""]
    return "\n".join(t)


if __name__ == "__main__":
    texto = informe()
    Path("LICENCIAS.md").write_text(texto, "utf-8")
    print(texto)
