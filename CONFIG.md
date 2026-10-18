# Configuración antes del primer uso

Hay **un solo valor** que cambiar, y aparece en dos sitios:

| Archivo | Línea |
|---|---|
| `README.md` | el badge «Abrir en Colab» del encabezado |
| `colab/pronostico_solar.ipynb` | la constante `REPO` de la primera celda |

```bash
RUTA="mi-usuario/mi-repo"
sed -i "s|<usuario>/pronostico-solar|$RUTA|g" README.md colab/pronostico_solar.ipynb
```

Verificar que quedó (debe mostrar su URL, no el marcador). El cuaderno conserva
a propósito otra línea con `<usuario>`: es la guarda que avisa si no se
configuró, así que no busque el marcador a secas.

```bash
grep -c '<usuario>/' README.md colab/pronostico_solar.ipynb   # debe dar 0 y 0
```

Después, verificar que el cuaderno encuentra los artefactos:

```bash
python -c "
import json, pathlib
r = json.loads(pathlib.Path('artefactos/resumen.json').read_text('utf-8'))
print(r['dias_evaluados'], 'días ·', r['mae_modelo_kw'], 'kW de MAE')"
```

Si `artefactos/` está vacío, regenerarlo. Tarda unos minutos y **no hace falta
para correr las pruebas**, solo para que el Colab abra sin entrenar:

```bash
python -m banco.artefactos   # ver la función generar()
```
