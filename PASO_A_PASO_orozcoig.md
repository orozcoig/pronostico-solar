# Paso a paso para publicar — usuario `orozcoig`, Windows con PowerShell

Todo con sus datos ya puestos y los comandos en la sintaxis de **PowerShell**,
que es la consola de Windows. Unos 20 minutos.

> **Por qué importa la consola.** `grep`, `sed`, `ls` y `cat` son de Linux y
> Mac; PowerShell no los reconoce y responde *«el término no se reconoce como
> nombre de un cmdlet»*. Abajo va el equivalente de cada uno, y al final una
> tabla de equivalencias. Lo que sí funciona igual en las dos es `python`,
> `pip` y `git`.
>
> Para abrir PowerShell en la carpeta correcta: en el Explorador, entre a
> `C:\proyectos\pronostico-solar`, haga clic derecho en un espacio vacío y
> elija **«Abrir en Terminal»**. O escriba `cd C:\proyectos\pronostico-solar`.

Al final va a tener un enlace que puede abrir usted o enviarle a alguien, y que
muestra la planta ficticia de **Medellín, 500 kWp DC / 400 kW AC**, con su
generación pronosticada contra la real.

---

## PARTE A — En su PC

### A1. Bajar los archivos

Descargue `pronostico-solar.zip` y descomprímalo. Debe quedar la carpeta
`pronostico-solar` con esta estructura:

```
pronostico-solar\
├── .github\workflows\banco.yml
├── .gitignore
├── banco\        ← 23 archivos .py
├── tests\        ← test_banco.py
├── colab\        ← pronostico_solar.ipynb
├── artefactos\   ← 6 archivos (2 .parquet, 3 .png, 1 .json)
├── README.md   CLAUDE.md   CONFIG.md   ESTADO.md   PUBLICAR.md
├── DEPENDENCIAS_FASE1.md   FASE2_COSTO_DEL_ERROR.md   LICENCIAS.md
├── LICENSE   pyproject.toml   pytest.ini   requirements-banco.txt
```

**Confirme que llegaron los dos que empiezan con punto** (`.github` y
`.gitignore`). Windows los oculta por defecto:

```powershell
Get-ChildItem -Force | Where-Object Name -like ".*"
```

Deben aparecer los dos. Sin `.gitignore` el repositorio se llena de archivos
temporales; sin `.github` no corren las pruebas automáticas.

Conteo rápido de que está todo:

```powershell
(Get-ChildItem banco\*.py).Count        # debe dar 23
(Get-ChildItem artefactos).Count        # debe dar 6
```

### A2. Cambiar la URL en dos archivos

Hay que reemplazar `<usuario>/pronostico-solar` por `orozcoig/pronostico-solar`.
Aparece **una vez en cada archivo**.

**Opción manual** (la más segura): abra cada archivo con el **Bloc de notas** y
use *Buscar y reemplazar*.

- En **`README.md`** está en la **línea 3**, dentro del botón «Abrir en Colab».
  Si lo abre en un visor de Markdown no lo va a ver como texto, porque esa
  línea se renderiza como un botón. Ábralo como texto plano.
- En **`colab\pronostico_solar.ipynb`** está en la línea que empieza con
  `REPO = `.

**Opción por PowerShell**, desde dentro de la carpeta:

```powershell
foreach ($f in "README.md", "colab\pronostico_solar.ipynb") {
    (Get-Content $f -Raw -Encoding UTF8) `
        -replace '<usuario>/pronostico-solar', 'orozcoig/pronostico-solar' |
        Set-Content $f -NoNewline -Encoding UTF8
}
```

**Verificar.** Esto no debe mostrar nada:

```powershell
Select-String -Path README.md, colab\pronostico_solar.ipynb -Pattern '<usuario>/' -SimpleMatch
```

Y esto debe mostrar **dos líneas**, una de cada archivo:

```powershell
Select-String -Path README.md, colab\pronostico_solar.ipynb -Pattern 'orozcoig' -SimpleMatch
```

> **No reemplace `<usuario>` a secas.** El cuaderno tiene otra línea que dice
> `<usuario>` **sin barra**: es la guarda que detiene la ejecución con un
> mensaje claro si alguien lo abre sin configurar. Por eso se busca el texto
> completo `<usuario>/pronostico-solar`, y por eso la verificación usa
> `<usuario>/` **con barra**.

### A3. Comprobar que funciona antes de publicar

```powershell
pip install -r requirements-banco.txt
python -m pytest tests/ -q -m "not lento"
```

**Debe terminar con `21 passed`.** Tarda un minuto largo.

Si falla aquí, va a fallar igual en GitHub y ahí queda a la vista. Si sale algo
en rojo, resuélvalo antes de seguir.

---

## PARTE B — Subirlo a GitHub

### Camino 1 — GitHub Desktop (recomendado, sin comandos)

1. Abra GitHub Desktop → **File → Add local repository**.
2. Elija `C:\proyectos\pronostico-solar`. Dirá que no es un repositorio todavía
   y ofrecerá **«create a repository»**: acepte.
3. Deje el nombre `pronostico-solar`. **No marque** «Initialize with README» ni
   elija licencia: ya los tiene y chocarían.
4. Abajo a la izquierda escriba el mensaje
   `Banco de pruebas y motor de pronóstico operativo solar` →
   **Commit to main**.
5. Arriba → **Publish repository**.
   **Desmarque «Keep this code private».** Si queda privado, Colab no puede
   abrirlo y el enlace no sirve para mostrárselo a nadie.

### Camino 2 — PowerShell con git

1. En **github.com** → **New** → nombre `pronostico-solar` → **sin** README,
   **sin** .gitignore, **sin** licencia → **Create repository**.
2. En PowerShell, dentro de la carpeta:

```powershell
git init
git add .
git status                 # revise que NO aparezcan __pycache__ ni .pytest_cache
git commit -m "Banco de pruebas y motor de pronostico operativo solar"
git branch -M main
git remote add origin https://github.com/orozcoig/pronostico-solar.git
git push -u origin main
```

---

## PARTE C — Comprobar

### C1. Que los artefactos subieron

Abra `https://github.com/orozcoig/pronostico-solar/tree/main/artefactos`

**Deben verse 6 archivos.** Si la carpeta está vacía o no existe, el cuaderno
no abre. Solución:

```powershell
git add -f artefactos/
git commit -m "Agregar artefactos"
git push
```

### C2. Que las pruebas automáticas pasan

Abra `https://github.com/orozcoig/pronostico-solar/actions`

El trabajo *Banco sintético* arranca solo y debe quedar en verde en unos
minutos.

---

## PARTE D — Abrir el cuaderno en Colab

**No hay que crear ni subir nada a Colab.** El cuaderno ya está en el
repositorio. Se abre con este enlace:

```
https://colab.research.google.com/github/orozcoig/pronostico-solar/blob/main/colab/pronostico_solar.ipynb
```

Ábralo y use **Entorno de ejecución → Ejecutar todo**.

Debe tardar **segundos**, no minutos: el cuaderno no entrena nada, solo lee los
artefactos que ya subió.

En la portada del repositorio quedó el botón **«Abrir en Colab»** que lleva al
mismo sitio.

---

## Qué va a ver

| | |
|---|---|
| Ubicación | Medellín, 6,25 N / 75,57 W |
| Capacidad | 500 kWp DC / 400 kW AC |
| Montaje | inclinación 15°, azimut 180°, estructura fija |
| Evaluación | 144 días no vistos por el modelo |
| Error | 47,7 kW de MAE, el 28,9 % de la generación media diurna |
| Incertidumbre | banda de 244 kW, el 61 % de la capacidad |

Cinco secciones: la gráfica de pronóstico contra real, la lectura en lenguaje
de negocio, el diagnóstico automático, cómo cargar datos propios, y qué falta
por decidir.

**Si quiere cambiar la planta** —otra ubicación, otra capacidad, otra
inclinación—, se edita `banco\sitios.py` y se regenera todo:

```powershell
python -m banco.generar_todo              # 24 meses, unos 6 minutos
python -m banco.generar_todo --rapido     # 4 meses, 30 segundos, solo para probar
```

Eso reescribe `artefactos\`; después hay que volver a subirla a GitHub. **La
opción `--rapido` da números distintos a propósito** (menos historia): sirve
para comprobar que el pipeline corre, no para citar cifras.

---

## Equivalencias de comandos

Por si encuentra instrucciones escritas para Linux o Mac en los otros
documentos del proyecto.

| Linux / Mac | PowerShell |
|---|---|
| `ls` | `Get-ChildItem` o `dir` |
| `ls -a` | `Get-ChildItem -Force` |
| `cat archivo` | `Get-Content archivo` |
| `grep texto archivo` | `Select-String -Path archivo -Pattern texto -SimpleMatch` |
| `grep -c texto archivo` | `(Select-String -Path archivo -Pattern texto -SimpleMatch).Count` |
| `sed -i "s/a/b/g" f` | `(Get-Content f -Raw) -replace 'a','b' \| Set-Content f` |
| `ls carpeta \| wc -l` | `(Get-ChildItem carpeta).Count` |
| `rm -rf carpeta` | `Remove-Item carpeta -Recurse -Force` |
| `python`, `pip`, `git` | iguales |

---

## Si algo sale mal

| Lo que ve | Qué pasó |
|---|---|
| `'grep' no se reconoce...` | Comando de Linux en PowerShell. Vea la tabla de arriba |
| No encuentro el texto en `README.md` | Lo está viendo en vista previa de Markdown. Ábralo con el Bloc de notas |
| `Falta configurar REPO...` en Colab | No hizo el paso A2, o solo en un archivo |
| `No encuentro artefactos en...` | La carpeta `artefactos/` no subió (ver C1) |
| Colab pide autenticación | El repositorio quedó privado. Settings → General → Change visibility |
| El cuaderno tarda minutos | Está regenerando algo. Revise que los `.parquet` estén en GitHub |
| En GitHub aparece `__pycache__` | Faltó el `.gitignore`. Bórrelos del repositorio y vuelva a subir |
| `git push` rechazado | El repositorio se creó con README. Haga `git pull --rebase origin main` primero |
