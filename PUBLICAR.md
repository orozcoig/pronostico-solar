# Cómo publicar el repositorio y abrir el cuaderno en Colab

Unos veinte minutos la primera vez. El cuaderno **no se crea**: ya existe en
`colab/pronostico_solar.ipynb`. Lo que se hace es publicarlo en GitHub y abrirlo
desde ahí.

---

## 1. Bajar los archivos

Descargue todos los archivos del proyecto a una carpeta local. Debe quedar así:

```
pronostico-solar/
├── .github/workflows/banco.yml
├── .gitignore
├── banco/            (23 archivos .py)
├── tests/            (test_banco.py)
├── colab/            (pronostico_solar.ipynb)
├── artefactos/       (2 parquet, 3 png, resumen.json)
├── README.md  CLAUDE.md  CONFIG.md  ESTADO.md
├── DEPENDENCIAS_FASE1.md  FASE2_COSTO_DEL_ERROR.md  LICENCIAS.md
├── LICENSE  pyproject.toml  pytest.ini  requirements-banco.txt
```

Verifique que esté completo antes de seguir:

```bash
cd pronostico-solar
ls banco/*.py | wc -l        # debe dar 23
ls artefactos/               # 6 archivos
python -m pytest tests/ -q -m "not lento"   # debe dar 21 passed
python -m pytest tests/ -q -m lento          # debe dar 2 passed
```

Si las pruebas no pasan localmente, no publique todavía: la integración
continua va a fallar igual y queda peor en público.

---

## 2. Crear el repositorio en GitHub

En **github.com → New repository**:

- **Nombre:** `pronostico-solar` (o el que prefiera)
- **Visibilidad:** público o privado, los dos funcionan. Público da Actions
  gratis sin límite; privado consume minutos de su cuenta.
- **NO marque** "Add a README", "Add .gitignore" ni "Choose a license": ya los
  tiene y GitHub crearía conflictos.

Copie la URL que le muestra, de la forma `https://github.com/USUARIO/REPO`.

---

## 3. Reemplazar la URL de ejemplo

Es lo único que hay que editar. Aparece en dos sitios.

```bash
RUTA="USUARIO/REPO"          # ← su usuario y repositorio, sin https ni .git
sed -i "s|<usuario>/pronostico-solar|$RUTA|g" README.md colab/pronostico_solar.ipynb

# Verificar: debe dar 0 en los dos archivos.
grep -c '<usuario>/' README.md colab/pronostico_solar.ipynb
```

En macOS use `sed -i ''` en lugar de `sed -i`.

> Dos detalles que hacen fallar el reemplazo si se improvisa:
>
> - La URL aparece en **dos formas distintas**: `https://github.com/<usuario>/...`
>   en el cuaderno y `colab.research.google.com/github/<usuario>/...` en el badge
>   del README. Por eso se reemplaza el tramo `<usuario>/pronostico-solar`, que
>   es común a las dos, y no la URL completa.
> - El cuaderno conserva **a propósito** una línea con `<usuario>` sin barra: es
>   la guarda que detiene la ejecución si alguien lo abre sin configurar. Por eso
>   se cuenta `<usuario>/` **con barra**, que sí debe desaparecer.

---

## 4. Subir

```bash
git init
git add .
git status                    # revise que NO aparezca __pycache__ ni .pytest_cache
git commit -m "Banco de pruebas y motor de pronóstico operativo solar"
git branch -M main
git remote add origin https://github.com/USUARIO/REPO.git
git push -u origin main
```

Si `git status` muestra `__pycache__` o `.pytest_cache`, falta el `.gitignore`
o no quedó en la raíz. Bórrelos y repita.

**Confirme que `artefactos/` sí subió.** Sin esos seis archivos el Colab no
abre. Si no aparecen, fuércelos con `git add -f artefactos/`.

---

## 5. Verificar la integración continua

Vaya a la pestaña **Actions** del repositorio. El workflow *Banco sintético*
debe arrancar solo con el primer push y pasar en unos minutos.

Si dice "Workflows aren't being run on this forked repository", habilítelos con
el botón que aparece ahí mismo.

---

## 6. Abrir el cuaderno en Colab

No hay que subir nada a Colab. Se abre directo desde GitHub:

```
https://colab.research.google.com/github/USUARIO/REPO/blob/main/colab/pronostico_solar.ipynb
```

Reemplace `USUARIO/REPO` y abra ese enlace. Luego **Entorno de ejecución →
Ejecutar todo**. Debe correr en segundos, porque no entrena nada: lee los
artefactos.

Para dejarlo a un clic, agregue este botón al principio del `README.md`:

```markdown
[![Abrir en Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/USUARIO/REPO/blob/main/colab/pronostico_solar.ipynb)
```

**Si el repositorio es privado**, Colab no puede clonarlo sin autenticación. Dos
salidas: hacerlo público, o que quien lo abra suba la carpeta `artefactos/` a
mano con el ícono de archivos de Colab.

---

## 7. Qué compartir con un cliente

El enlace de Colab, no el del repositorio. El cliente no necesita ver el
código; necesita ver su generación pronosticada contra la real y la lectura de
negocio.

Antes de enviarlo, **ábralo usted desde una ventana de incógnito** y recorra
las cinco secciones como si fuera él. La sección 5 —qué no sabemos todavía—
está ahí a propósito: si alguien pregunta por ella, es la conversación que
quiere tener.

---

## Problemas frecuentes

| Síntoma | Causa |
|---|---|
| `Falta configurar REPO...` en la primera celda | No se hizo el paso 3 |
| `No encuentro artefactos en...` | `artefactos/` no subió al repositorio |
| El Colab tarda minutos | Está regenerando algo: no debería. Revise que los parquet estén en el repositorio |
| Las pruebas fallan en Actions pero pasan local | Versiones distintas. Fije versiones exactas en `requirements-banco.txt` |
| `git push` rechazado | El repositorio se creó con README. Haga `git pull --rebase origin main` primero |
