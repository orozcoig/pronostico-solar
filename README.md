# ☀️ Pronóstico operativo solar — banco de pruebas y motor

[![Abrir en Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/orozcoig/pronostico-solar/blob/main/colab/pronostico_solar.ipynb)

Predecir la generación horaria de una planta fotovoltaica existente, con
horizonte de horas a días, y **poder demostrar cuánto de esa predicción es
mejora real y cuánto es suerte**.

El repositorio no es un modelo. Es la infraestructura para saber si un modelo
sirve: un banco de pruebas con fallas de causa conocida, un contrato de datos
que hace intercambiable la fuente, una vara estadística escrita antes de
probar, y criterios de muerte numéricos pactados antes de empezar.

> **Alcance.** Solo pronóstico operativo de una planta que ya opera y tiene
> medición histórica. Quedan fuera la estimación de producción antes de
> invertir (es simulación física, no aprendizaje) y la verificación de
> desempeño (es hindcast con clima observado, reglas opuestas). Si no hay
> medición horaria con doce meses, no es un proyecto de pronóstico.

## Cómo funciona

```
                      ┌──────────────────────────────────────────┐
                      │  FuenteDeDatos (contrato)                │
                      │  as_of obligatorio · UTC · pronóstico     │
                      │  indexado por instante de emisión         │
                      └──────────────┬───────────────────────────┘
          ┌──────────────────────────┼──────────────────────────┐
   FuenteSintetica              FuenteCSV                 (FuenteSCADA)
   planta + clima + fallas      archivos del cliente       por escribir
          └──────────────────────────┼──────────────────────────┘
                                     ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │ agente       │   │ lineas_base  │   │ modelo       │   │ diagnostico_ │
   │ (datos)      │──▶│ + vara       │──▶│ (Fase 6)     │──▶│ modelo       │
   │ 10 fallas    │   │ 3 referencias│   │ q10/q50/q90  │   │ (Fase 7)     │
   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                                     ▼
                     calificacion · criterios · artefactos · Colab
```

## Correr

Antes del primer uso hay **un solo valor** que configurar (la URL del
repositorio, en dos sitios). Ver `CONFIG.md`.

```bash
pip install -r requirements-banco.txt
pytest tests/ -q -m "not lento"        # contrato + diagnóstico, ~1 min
pytest tests/ -q -m lento              # series de 24 meses
python -m banco.tablero                # acierto diagnóstico, 11 escenarios
python -m banco.curva                  # potencia diagnóstica vs meses de historia
```

Para regenerar todo desde cero (planta, pronóstico, modelo y artefactos):

```bash
python -m banco.generar_todo              # 24 meses, ~6 min
python -m banco.generar_todo --rapido     # 4 meses, ~30 s, solo para verificar
```

El cuaderno que abre el cliente está en `colab/pronostico_solar.ipynb`. No
entrena nada: lee los artefactos precomputados de `artefactos/`, que **se
versionan a propósito** —si el cliente tiene que regenerarlos, el cuaderno deja
de abrir en segundos y deja de abrirse—. Se regeneran con `banco.artefactos`.

La serie de 5 minutos, en cambio, no se versiona: pesa cientos de MB y es
reproducible por semilla.

## Qué hay

| Módulo | Qué hace |
|---|---|
| `contrato` | La frontera. Metadatos, `Protocol FuenteDeDatos`, validadores |
| `fuente` / `fuente_csv` | Dos implementaciones del contrato. Dos, no una, a propósito |
| `clima` / `planta` | Generador sintético: cadena de Markov sobre índice de cielo despejado, cadena física con pvlib |
| `pronostico` | Degradador: sesgo de nubosidad, error de temporización, suavizado y dispersión crecientes |
| `fallas` | Diez fallas inyectables en tres capas: verdad, medición, pronóstico |
| `mediciones` | Los detectores, uno por falla, con su umbral |
| `agente` | Diagnóstico de datos, en orden de dependencia |
| `calificacion` / `tablero` / `curva` | Criterio de aprobación 3.4, control negativo 3.5, potencia vs historia |
| `lineas_base` / `vara` / `backtest` | Tres referencias, diferencias pareadas con bootstrap de bloques, arnés con corte as-of |
| `modelo` | Conjunto operativo, partición por bloques, árboles con pérdida cuantílica |
| `diagnostico_modelo` | La matriz de la Fase 7 sobre los residuos |
| `criterios` | Los diez criterios de muerte, evaluables |
| `artefactos` | Parquet, figuras y resumen de negocio para el Colab |

## Resultados medidos

Sobre la planta sintética de referencia (Medellín, 500 kWp DC / 400 kW AC).
**No son transferibles a un sitio real**; demuestran el método.

| | |
|---|---|
| Acierto diagnóstico | 11 de 11 escenarios, con control negativo limpio |
| Potencia vs historia | 9 de 10 fallas con 6 meses; suciedad necesita 24 |
| Mejor línea base | modelo físico, 53,0 kW (32,1 % nMAE) |
| Modelo (árboles, q50) | 47,7 kW (28,9 %), supera la vara de 1,99 kW |
| Techo alcanzable | 6,1 kW — **el 87 % del error es del proveedor meteorológico** |
| Banda 10–90 | 244 kW de ancho (61 % de la placa), cobertura 84,7 % |

### Qué compra cada técnica sobre el error importado

Medido contra la vara, no estimado. Un solo miembro del proveedor es la referencia.

| Técnica | MAE | Cambio | Veredicto |
|---|---|---|---|
| Pronóstico crudo (1 miembro) | 47,98 kW | — | referencia |
| Otro miembro del mismo proveedor | 45,56 | −2,42 (vara 2,91) | sin efecto |
| Post-proceso de sesgo del NWP | 48,10 | +0,12 (vara 0,68) | **sin efecto** |
| Mezcla de dos proveedores | 44,53 | −3,46 (vara 1,43) | mejora |
| **Ensamble de 5 miembros** | **37,73** | **−10,26 (vara 2,05)** | **mejora** |

Dos hallazgos que refinan la matriz de la Fase 7:

- **El post-proceso del NWP no aporta nada cuando el consumidor es un modelo
  aprendido**, porque el modelo ya absorbe ese sesgo. Verificado por prueba
  independiente: sobre un modelo *físico*, que no aprende, el mismo
  post-proceso sí gana 1,55 kW contra una vara de 1,46. La técnica aplica
  según **quién consume el pronóstico**, no solo según de dónde viene el error.
- **El ensamble meteorológico es la técnica que más compra**, y le gana a la
  mezcla de dos proveedores por 6,80 kW contra una vara de 1,96.

Barrido de número de miembros, cada paso contra la vara del anterior:

| Miembros | MAE | vs 1 miembro | vs anterior | ¿gana? |
|---|---|---|---|---|
| 1 | 46,19 kW | — | — | referencia |
| 2 | 42,70 | −3,48 | −3,48 (vara 1,63) | sí |
| 3 | 40,08 | −6,10 | −2,62 (vara 1,25) | sí |
| 5 | 37,73 | −8,46 | −2,35 (vara 1,05) | sí |
| 9 | 36,40 | −9,78 | −1,32 (vara 0,88) | sí |

Rendimientos decrecientes pero **cada paso sigue superando la vara hasta nueve
miembros**: el piso no se alcanzó. Lo que sí se agota rápido es el valor por
miembro: del primero al tercero se compran 6,1 kW, del tercero al noveno
apenas 3,7 más.

La dispersión entre miembros —mediana 72 W/m², p90 161 W/m²— es el insumo
natural de una banda calibrada: dice en qué horas el proveedor mismo no sabe.

## Principios que el código obedece

1. **Medir antes de optimizar.** Sin vara no se distingue una mejora de la suerte.
2. **Una mejora espectacular es fuga de información hasta que se demuestre lo contrario.**
3. **Un backtest que entrena con clima mejor que el disponible en operación miente.** Por eso `as_of` es obligatorio en la firma y el pronóstico se indexa por instante de emisión.
4. **Separar dato de supuesto.** `MetadatosSitio.campos_supuestos` lo hace consultable en tiempo de ejecución.
5. **El orden de diagnóstico es dependencia, no preferencia.** Alineación → calidad → nivel de capacidad → operación → equipo → geometría → degradación → meteorología. Cada etapa puede contaminar a la siguiente, y está medido.

## Lo que todavía no está

- `FuenteSCADA`: el contrato tiene dos implementaciones; falta la de un historiador real.
- Simulación de liquidación en pesos y valor anual: bloqueados por la Fase 1.
- Dos puntos ciegos medidos del diagnóstico de modelo: pérdida desalineada y features faltantes. Documentados en `diagnostico_modelo`, no tapados.
- **El banco no puede evaluar el valor de la dispersión del ensamble.** Sus
  miembros difieren solo por el sorteo de los mismos mecanismos, así que su
  dispersión es predecible desde el campo medio (R² = 0,87) y no aporta nada
  como feature. Un ensamble real sí lleva información independiente. Para
  probarlo haría falta generar miembros con estructuras de error distintas
  entre sí; está documentado en `pronostico`.

Ver `DEPENDENCIAS_FASE1.md` para qué número depende de qué decisión pendiente,
`FASE2_COSTO_DEL_ERROR.md` para qué cuesta el error según el rol regulatorio del
cliente — que es lo que decide si hay proyecto—, y `GUION_PRIMERA_REUNION.md`
para el checklist de entrada y los tres números que van en la primera reunión.

## Licencias

Todo el stack es permisivo y apto para uso comercial; ver `LICENCIAS.md`, con
las licencias verificadas desde los archivos instalados, no desde páginas web.
