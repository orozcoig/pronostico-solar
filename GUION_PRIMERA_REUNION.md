# Guion de la primera reunión

Para usar frente a un cliente potencial, antes de cotizar nada.

**La regla que ordena todo este documento:** los números incómodos se dicen en
la **primera reunión**, no en la entrega. Es el mismo dato, pero dicho antes lo
hace ver a usted como alguien que sabe de lo que habla; dicho después parece
una excusa.

---

## Parte 1 — El checklist de entrada

Las cinco preguntas, en orden. **Las dos primeras pueden terminar la
conversación**, y terminarla temprano es barato.

### P1. ¿Qué rol regulatorio tiene y cómo se liquida?

En Colombia, **un autogenerador de hasta 1 MW se liquida por período de
facturación, no por hora**. Equivocarse a las 10 de la mañana y compensarse a
las 3 de la tarde cuesta exactamente cero.

Si ese es el caso, **no hay un motor de pronóstico que vender** para liquidar.
Quedan dos salidas legítimas, y son conversaciones distintas:

- Que su **contrato privado** imponga una penalidad que la regulación no impone.
- Que haya **valor operativo** —baterías, cargas desplazables, programación de
  mantenimiento— que no pasa por el mercado.

Verificar con `criterios.m11_rol_expuesto_al_error`. Detalle en
`FASE2_COSTO_DEL_ERROR.md`.

### P2. ¿Tiene medición horaria con doce meses?

Pida un archivo con la generación hora a hora del último año. Deben ser unas
8.760 filas. **Sin eso no es un proyecto de pronóstico**, y hay que decirlo
antes de cotizar.

Verificar con `criterios.m1_historia_minima`.

### P3. ¿Existe archivo de los pronósticos del tiempo que recibió en su momento?

**Esta es la que más falla, y casi nadie la pregunta.**

No sirve el clima que efectivamente ocurrió: hace falta lo que el proveedor
*dijo que iba a pasar*, guardado día por día. Entrenar con el clima real en su
lugar produce un modelo que promete lo que nunca va a cumplir en operación.

Si no existe, cambia el **cronograma** —hay que acumular archivo— no la
metodología.

Verificar con `criterios.m2_archivo_de_pronostico`.

### P4. ¿Alguien cambia una decisión por saber qué pasa mañana?

La pregunta literal, para hacérsela a quien opera la planta:

> «Si yo le digo esta noche cuánto va a producir mañana hora por hora, ¿qué
> hace usted distinto?»

Si la respuesta es «nada», **el pronóstico vale cero por bueno que sea**.

Decisiones que sí cambian: cuánta energía comprometer en un contrato, cuándo
cargar una batería, cuándo programar un mantenimiento, cuándo correr una
máquina que consume mucho.

### P5. ¿A qué hora hay que emitir el pronóstico y cuánto cuesta equivocarse?

El horizonte lo impone el trámite que obliga al pronóstico, no el analista. Y
si equivocarse de más cuesta distinto que equivocarse de menos, **la métrica no
es el error promedio** y el modelo se construye distinto.

### Resumen

| Si el cliente… | Veredicto |
|---|---|
| Es autogenerador ≤ 1 MW liquidado por mes | **No**, salvo contrato privado o valor operativo |
| Tiene menos de 12 meses de medición horaria | **Todavía no** |
| No tiene archivo de pronósticos pasados | **Cambia el cronograma**, no el método |
| Nadie cambia una decisión por el pronóstico | **No.** Vale cero |
| Cumple las cinco | **Sí.** Empezar por el diagnóstico |

---

## Parte 2 — Los tres números que van en esta reunión

### Número 1 — «No espere la precisión que ve en las noticias»

Cuando se habla de pronóstico solar normalmente se habla del **país entero**.
Ahí los pronósticos son buenos, porque cuando se nubla en Medellín sigue
habiendo sol en el Caribe y el total casi no se mueve.

**Una planta sola es otra cosa: una nube la apaga completa.**

> «A un día de anticipación lo que puedo garantizar es un rango, y ese rango es
> ancho — más de la mitad de la capacidad de su planta. Si usted esperaba un
> número exacto, eso no existe para una planta individual, ni mío ni de nadie.»

Medido en el banco: la banda honesta al mediodía va **de 0 a 360 kW** en una
planta de 400 kW. El extremo inferior es **cero**: uno de cada diez días, al
mediodía, está completamente cubierta.

### Número 2 — «La mayor parte del error no es mía ni la puedo arreglar»

Del error total, **el 87 % viene de que el pronóstico del tiempo falló**. Solo
el 13 % es del modelo.

> «Yo puedo mejorar mi parte, que es pequeña. La parte grande depende de quién
> le vende el pronóstico del tiempo. Si alguien le promete reducir el error a
> la mitad sin hablar de eso, le está prometiendo algo que no controla.»

### Número 3 — «Hay algo barato que mueve más la aguja que contratarme»

| | Cuánto baja el error |
|---|---|
| Pedirle el ensamble al proveedor | **10,3 kW** |
| Todo el trabajo de modelado | 5,1 kW |

Decir esto parece ir contra uno mismo. Es lo que convierte una conversación
comercial en una asesoría — y si el cliente lo pide y el error baja, usted ya
demostró que sus números son ciertos antes de cobrar nada.

---

## Parte 3 — Qué es un ensamble, explicado para el cliente

Un pronóstico del tiempo parte de «cómo está la atmósfera ahora mismo», y ese
punto de partida nunca se conoce con exactitud.

Entonces los meteorólogos corren el mismo cálculo **varias veces**, cambiando
un poco el punto de partida cada vez. Si las diez corridas dan resultados
parecidos, hay confianza. Si dan resultados muy distintos, el día es incierto.

**Es como preguntarle a diez meteorólogos en vez de a uno.**

Se ganan dos cosas:

- **El promedio es más preciso** que cualquier corrida suelta: los errores de
  unas se cancelan con los de otras.
- **La dispersión dice en qué días desconfiar**, información que una sola
  corrida no da.

**Suele costar poco o nada porque el proveedor ya lo calcula.** Así es su modelo
por dentro. Entrega una sola corrida porque es más simple y porque nadie pide
lo demás.

---

## Parte 4 — Quién vende pronóstico del tiempo

**Especializados en solar.** Entregan irradiancia y potencia fotovoltaica
directamente, no «va a estar nublado».

- **Solcast** — empresa de datos solares adquirida por DNV en 2023. Irradiancia
  derivada de satélite, potencia fotovoltaica, histórico y pronóstico vía API.
  Afirma superar a los modelos meteorológicos globales en 25 % a día adelante y
  50 % a una hora. Tiene nivel gratuito para probar.
- **Vaisala Xweather** — marca bajo la cual Vaisala agrupó sus servicios de
  datos meteorológicos desde 2022.

**Genéricos con datos solares.**

- **Open-Meteo** — el que usa este proyecto en modo real. Gratuito para uso no
  comercial; **uso comercial requiere plan de pago** (verificar términos
  vigentes antes de usarlo con un cliente).
- **Forecast.Solar** — más sencillo, sin cuenta para el servicio público.

**Agencias públicas.** IDEAM en Colombia; modelos globales abiertos como GFS
(Estados Unidos) y ECMWF (Europa).

### Las dos preguntas que hay que hacerle al proveedor

Y que casi nadie hace:

1. **¿Me pueden entregar el ensamble en vez de una sola corrida?**
2. **¿Guardan el archivo de los pronósticos pasados, y me lo pueden dar?**

La primera es lo que más baja el error. La segunda es la condición para poder
entrenar un modelo honesto. Las dos suelen estar disponibles y rara vez se
piden.

---

## Parte 5 — Qué vender primero: el diagnóstico

**Qué es:** un trabajo corto, de **precio fijo**, con los datos que el cliente
ya tiene. No se construye ningún modelo de producción.

**Cómo funciona, en tres pasos:**

1. Un modelo simple con **el pronóstico del tiempo que el cliente recibió**.
   Se mide el error. En el banco: 48 kW.
2. Lo mismo, pero **reentrenado con el clima que realmente ocurrió** —que ya
   está registrado—. Se mide otra vez. En el banco: 6 kW.
3. La diferencia, 42 kW, es lo que aporta el proveedor meteorológico.

**Detalle técnico que no se puede saltar:** en el paso 2 hay que **volver a
entrenar**. Cambiarle solo el insumo a un modelo ya entrenado da un resultado
falso —medido: 10 % en vez de 3,7 %— porque ese modelo aprendió a corregir los
defectos del pronóstico y sigue corrigiéndolos sobre un clima que ya no los
tiene.

**Por qué precio fijo:** no se promete precisión, se promete **medición**. El
cliente paga por saber cuánta mejora hay disponible, no por una mejora.

**Y puede terminar en «no siga».** Si el diagnóstico concluye que casi todo el
error es del proveedor, la recomendación es cambiarle la petición al
meteorólogo, no construir un motor. Esa conclusión también vale dinero, y es
mucho más barata que descubrirla después.

---

## Parte 6 — Lo que NO hay que prometer

- **Precisión.** Se promete medición y un rango honesto.
- **Un porcentaje de mejora.** Sin conocer el reparto del error y la métrica
  del cliente, cualquier cifra es invención.
- **Que el pronóstico dé certeza.** No la da. La certeza se compra con un
  contrato distinto, una batería o un margen — y todas cuestan.
- **Pronóstico a un cliente que no cambia ninguna decisión con él.**

---

## Fuentes

- Costo del error por rol regulatorio: `FASE2_COSTO_DEL_ERROR.md`
- Qué depende de decisiones pendientes: `DEPENDENCIAS_FASE1.md`
- Criterios evaluables: `banco/criterios.py`
- Estado del proyecto: `ESTADO.md`

Verificado en octubre de 2026. **La regulación colombiana sobre desviaciones de
generación variable está en movimiento activo**: confirmar vigencia antes de
usar estas cifras con un cliente.
