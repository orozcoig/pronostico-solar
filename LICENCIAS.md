# Auditoría de licencias

Generada con `python -m banco.licencias`, leyendo lo **instalado**: primero
el metadato normativo `License-Expression`, luego el archivo de licencia de
la raíz del `dist-info`, y si la rueda no lo empaqueta —ocurre según la
plataforma— el nombre declarado en el campo `License`. El olfateo de texto
queda como último recurso y se marca para revisión manual.

| Paquete | Versión | Licencia | Fuente | Método | Para qué |
|---|---|---|---|---|---|
| `pvlib` | 0.16.1 | **BSD-3-Clause** | `metadato License-Expression` | normativo | Física solar: posición, cielo despejado, transposición, temperatura de celda, inversor |
| `pandas` | 3.0.2 | **BSD-3-Clause** | `LICENSE` | archivo raíz | Series de tiempo |
| `numpy` | 2.4.4 | **BSD-3-Clause (+ componentes: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0)** | `metadato License-Expression` | normativo | Numérico |
| `scipy` | 1.17.1 | **BSD-3-Clause** | `LICENSE.txt` | archivo raíz | Bootstrap de bloques, filtros, distribuciones |
| `scikit-learn` | 1.8.0 | **BSD-3-Clause** | `metadato License-Expression` | normativo | Árboles con gradiente y pérdida cuantílica |
| `matplotlib` | 3.10.8 | **PSF-2.0 (Matplotlib License)** | `LICENSE` | archivo raíz | Figuras |
| `pyarrow` | 26.0.0 | **Apache-2.0** | `metadato License-Expression` | normativo | Parquet de artefactos |
| `pvanalytics` | 0.2.2 | **MIT** | `LICENSE` | archivo raíz | Segunda implementación: desfase horario, recorte, saltos de nivel |
| `ruptures` | 1.1.10 | **BSD-2-Clause** | `licenses/LICENSE` | archivo raíz | Dependencia transitiva de pvanalytics (detección de puntos de cambio) |
| `rdtools` | 3.2.1 | **MIT** | `licenses/LICENSE` | archivo raíz | Segunda implementación: ensuciamiento (método SRR) |

## Veredicto

**Ninguna dependencia impide uso comercial.** No hay copyleft fuerte.

## Notas

- `numpy` declara `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`: es
  BSD-3 con componentes empotrados bajo otras licencias permisivas. Un
  escáner que recorre subcarpetas reporta MIT y se equivoca.
- `ruptures` era el pendiente abierto del memo inicial de librerías. Entra
  como dependencia transitiva de `pvanalytics`; es BSD-2-Clause.
- `pvanalytics` y `rdtools` son opcionales (`pip install -e .[cruce]`): sirven
  para cruzar los detectores propios contra implementación independiente. El
  pipeline corre sin ellas.
- **Descartadas:** SAM/PySAM (binario pesado, redundante con pvlib),
  pvfactors (solo bifacial y seguidores), solar-data-tools (resuelve otro
  problema: análisis sin etiquetas).
- **Fuera de alcance de esta auditoría:** la política de uso comercial de los
  **datos** de Open-Meteo y de XM. El banco sintético no llama a ninguna de
  las dos. La licencia del cliente de software y la de los datos que entrega
  son cosas distintas, y la segunda hay que verificarla con fuente actual
  antes de usar datos reales.
