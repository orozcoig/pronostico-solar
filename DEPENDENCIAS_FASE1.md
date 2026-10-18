# Qué depende de la Fase 1 — y qué restringe en lo ya medido

La Fase 1 no se ha hecho porque no hay cliente. Todo lo construido corre igual,
pero **hay decisiones que se tomaron por defecto y que la Fase 1 puede invalidar**.
Este archivo lleva la cuenta: qué se supuso, qué número depende de ese supuesto,
y qué habría que rehacer si la respuesta real es otra.

Regla de lectura: la **estructura** del banco es independiente del cliente; sus
**parámetros y sus números** no lo son. Ningún valor de este repositorio es
transferible a una propuesta hasta que la Fase 1 cierre.

---

## D1 — Hora de emisión y horizonte efectivo

**Supuesto:** emisión a las 12:00 UTC del día anterior, horizonte 12–36 h
(día adelante). Archivo de pronóstico con ciclos 00 y 12 UTC y alcance 72 h.

**Lo impone el trámite, no el analista.** La hora de cierre del proceso que
obliga al pronóstico es la que fija el horizonte, y nadie la ha preguntado.

**Qué restringe hoy:**

| Número medido | Valor | Depende |
|---|---|---|
| MAE del modelo q50 | 47,96 kW (29,0 % nMAE) | sí, fuertemente |
| MAE del modelo físico | 53,02 kW | sí |
| Error del pronóstico por horizonte | 25,1 % / 30,2 % / 35,5 % a 1–24 / 24–48 / 48–72 h | es la medición de la dependencia |
| Ancho del intervalo 10–90 | 244 kW (61 % de la placa) | sí |

**Si el horizonte es intradiario (0–6 h)** todo cambia de naturaleza, no de
magnitud: manda la persistencia y la observación reciente, no el modelo
meteorológico. Ninguna feature actual mira la generación de horas previas, así
que el conjunto de entrenamiento habría que reconstruirlo. La fracción de error
importada del meteorológico —hoy 87 %— caería mucho, y con ella la conclusión
principal de la Fase 7.

**Si el horizonte es más allá de 72 h**, manda la climatología y las tres líneas
base cambian de orden.

**Qué habría que rehacer:** el conjunto operativo, las tres líneas base, el
modelo, la vara y el experimento de techo alcanzable. Es decir, casi todo lo
numérico. El código no.

---

## D2 — Estructura de penalidad: cuánto cuesta pasarse y cuánto quedarse corto

**Supuesto:** penalidad **simétrica**, por eso la métrica usada es MAE y el
modelo de referencia es el q50 (la mediana minimiza el MAE).

**Qué restringe hoy:** la elección del cuantil, y con ella toda la Fase 6.

Medido en el bloque de prueba, pérdida pinball de cada cuantílico contra el
modelo de media:

| Cuantil | Modelo cuantílico | Modelo de media |
|---|---|---|
| q10 | 16,52 | 24,47 |
| q50 | 23,87 | 25,17 |
| q90 | **9,07** | 25,87 |

Si la penalidad es asimétrica, **el pronóstico óptimo no es la mediana sino un
cuantil, y cuál lo determina la razón entre ambos costos**. En q90 el modelo de
media es casi tres veces peor que el cuantílico correspondiente: elegir mal el
cuantil cuesta más que cualquier mejora de modelo lograda hasta ahora.

**Riesgo concreto:** la tabla de Fase 6 —q50 gana a las tres líneas base por
5,06 kW contra una vara de 1,99— está escrita contra la métrica equivocada si
la penalidad resulta asimétrica. No se invalida el modelo; se invalida el
veredicto.

**Ya ocurrió una vez en este proyecto:** la primera corrida de Fase 6 entrenó
con pérdida cuadrática y evaluó con MAE, y el q50 le ganó por 2,58 kW. Alinear
la pérdida con la métrica duplicó el margen sobre la línea base difícil, de
2,46 a 5,06 kW. Es la primera fila de la matriz de Fase 7 —objetivo
desalineado, y hasta resolver eso no aplica nada más— y la prueba de que esta
dependencia no es teórica.

---

## D3 — Métrica de negocio antes que métrica técnica

**Supuesto:** MAE en horas con generación por encima del 2 % de la capacidad AC.

**Qué restringe:** el piso de 2 % es arbitrario. Se eligió porque incluir las
horas de noche diluye el error con ceros que ningún modelo falla y hace que
todos los modelos se parezcan. Pero si la liquidación es por energía diaria, o
por bloques horarios, o con franquicia, la métrica no es MAE horario y **la
función de pérdida debe reflejarlo**.

Si la penalidad es escalonada —banda muerta y luego castigo— ninguna pérdida
continua la representa bien, y la comparación por MAE puede ordenar los modelos
distinto que la liquidación en pesos.

**Qué falta para cerrarlo:** simulación de liquidación en pesos. Está declarada
como salida por defecto de la Fase 1 y hoy no existe en el repositorio.

---

## D4 — Salida puntual o probabilística

**Supuesto:** se construyeron las dos. El q50 es puntual; q10/q50/q90 con
post-proceso monótono dan el intervalo.

**Medido:** cobertura del intervalo 10–90 = **84,7 %** contra 80 % nominal
(conservador, algo ancho). Ancho mediano **244 kW**, el 61 % de la placa.

**Qué restringe:** si el consumidor del dato solo ingiere un número, el
intervalo no se usa y el trabajo de cuantiles no se cobra. Si ingiere una
distribución, la evaluación correcta es pinball o CRPS y no MAE, y la tabla de
Fase 6 hay que rehacerla con esa métrica.

**Pendiente que depende de esto:** CRPS no está implementado. Se implementa
cuando se sepa si hay consumidor que lo use.

---

## D5 — El consumidor del dato

**Supuesto:** ninguno. No se ha definido qué sistema ingiere el pronóstico.

**Qué restringe:** **un pronóstico que ningún sistema ingiere vale cero.** Esto
no cambia ningún número del repositorio; cambia si alguno de ellos importa.
También decide el formato, la hora de entrega, los modos de falla y a quién se
avisa, que son el contenido de la Etapa 3 y no se pueden cotizar sin esto.

---

## D6 — Rol comercial del cliente y objetivo del modelo

> **ACTUALIZADO con la Fase 2 (octubre 2026).** Esta dependencia dejó de ser
> una precaución y pasó a ser el riesgo principal del proyecto. Una planta de
> 500 kWp es AGPE (límite 1 MW), y **un AGPE se liquida por período de
> facturación, no por hora**: su error de pronóstico horario no tiene precio
> regulatorio. Ver `FASE2_COSTO_DEL_ERROR.md`. El rol no solo cambia el
> objetivo del modelo: decide si hay proyecto.

**Supuesto:** se pronostica **generación bruta a la salida del inversor**, que
es lo que el usuario decidió como punto de medición.

**Riesgo no resuelto:** si el cliente es autogenerador, lo que se liquida es la
**exportación**, que es generación menos autoconsumo. El autoconsumo industrial
es un proceso estocástico distinto, no meteorológico. **Pronosticar generación
bruta no pronostica la cantidad que se liquida.** Si ese es el caso, el objetivo
del modelo cambia y con él el conjunto entero.

**Qué restringe:** todo lo medido supone que generación bruta es el objetivo
correcto. Si no lo es, el 87 % de error importado del meteorológico baja, porque
una parte del error nuevo vendría del lado de la carga, no del clima.

---

## D7 — Profundidad del archivo de pronóstico

**Supuesto:** existe archivo de corridas pasadas con 24 meses de profundidad y
dos emisiones diarias, porque el banco lo genera.

**Riesgo:** con un cliente real, **si el archivo de corridas pasadas no tiene
profundidad suficiente, cambia el cronograma**, no la metodología. Entrenar con
reanálisis o con la mejor corrida posterior es la fuga más cara del proyecto y
no es una alternativa aceptable.

**Qué restringe:** la partición 425 / 137 / 144 días supone esa profundidad. Con
menos archivo, el bloque de prueba se encoge y la vara crece: hoy la vara para
entrar la red es 1,99 kW sobre 144 días de prueba; con la mitad de días sería
del orden de 2,8 kW, y la red tendría que ganar más para contar.

---

## Lo que NO depende de la Fase 1

Para que el registro sea útil hay que decir también qué queda firme:

- El contrato de datos, incluido `as_of` obligatorio y el pronóstico indexado
  por instante de emisión.
- El banco sintético completo: las diez fallas, sus mediciones, el criterio de
  acierto diagnóstico y el control negativo.
- La curva de potencia diagnóstica: **nueve de diez fallas son diagnosticables
  con seis meses de historia; la suciedad necesita veinticuatro.**
- La partición temporal por bloques con separación, y el rechazo de la partición
  aleatoria.
- El método de la vara: diferencias pareadas y bootstrap de bloques.
- El hallazgo de que el experimento del techo alcanzable exige **reentrenar**,
  no solo cambiar el insumo: hacerlo mal da 10,0 % de nMAE en vez de 3,7 %.
- Que el post-proceso del NWP aplica según **quién consume el pronóstico**: nada
  sobre un modelo aprendido, 1,55 kW sobre un modelo físico.
- Que el ensamble meteorológico compra 10,26 kW de los 47,98, contra una vara
  de 2,05.

---

## Qué pasa si la Fase 1 nunca se hace

Se puede entregar el banco sintético y el diagnóstico de datos, porque no
dependen de cliente. No se puede cotizar la Etapa 2 ni la Etapa 3, y no se puede
afirmar ninguna cifra de mejora, porque **la mejora se mide contra una métrica
que todavía no está definida**.
