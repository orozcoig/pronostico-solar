# Costo unitario del error de pronóstico, por rol — Fase 2, punto 2

Las reglas difieren tanto entre roles que **el mismo error de pronóstico puede
valer decenas de millones al año o exactamente cero**. Este documento separa lo
verificado con fuente de lo supuesto, y marca lo que está en proyecto y no en
firme.

Consultado en octubre de 2026. **Verificar vigencia antes de usarlo con un
cliente**: la regulación colombiana sobre desviaciones de generación variable
está en movimiento activo, con varios proyectos en trámite.

---

## Hallazgo que condiciona todo lo demás

**Una planta de 500 kWp en Colombia es un AGPE, y un AGPE no paga desviaciones
horarias.**

El límite para autogenerador a pequeña escala es 1 MW de capacidad instalada,
definido por la Resolución UPME 281 de 2015 y usado por la Resolución CREG 174
de 2021. Nuestra planta de referencia está por debajo con holgura.

La liquidación de un AGPE es **por período de facturación**, no horaria: al
cierre de cada período los excedentes se parten en dos, los que igualan la
importación —reconocidos como créditos de energía si usa FNCER— y los que la
superan, valorados a una variable de mercado. Los excedentes se tratan como una
**reducción de la demanda** del comercializador.

**Consecuencia directa:** el error de pronóstico horario de un AGPE no tiene
precio regulatorio. Lo que se liquida es la energía neta del mes. Equivocarse a
las 10 de la mañana y compensarse a las 3 de la tarde cuesta cero.

Esto dispara el criterio **M10** y probablemente **M5** para ese rol: no hay
valor que justifique un motor de pronóstico. **Hay que decirlo antes de
cotizar**, no después.

Queda una vía legítima de valor para un AGPE, y es distinta: **no pronosticar
para liquidar, sino para operar** — decidir cuándo cargar una batería, cuándo
correr una carga desplazable, cuándo programar mantenimiento. Ahí el valor no
viene del mercado sino del proceso del cliente, y hay que cuantificarlo con él.
No es la Fase 2 que está escrita; es otra conversación.

---

## Los tres roles

### 1. Generador despachado centralmente

El que sí paga desviaciones. Para plantas de **generación variable** —solares,
eólicas y filo de agua despachadas centralmente—, el tratamiento viene de la
Resolución CREG 060 de 2019 y está siendo revisado.

Un proyecto de resolución en trámite propone una estructura de **franjas con
banda muerta**: una desviación horaria menor o igual al 10 % no se considera
desviación, y por encima se escalona hasta una cuarta franja de más del 30 %.

> **Esto está en PROYECTO, no en firme.** La serie 701 de CREG numera proyectos
> de resolución; la serie 101 numera resoluciones expedidas. Antes de construir
> una función de pérdida sobre estas franjas hay que confirmar cuál quedó
> vigente.

**Qué implica si queda así, y es la implicación central de todo este
documento:** con banda muerta y escalones, **la métrica no es MAE**. Un error
del 9 % cuesta cero y uno del 11 % cuesta todo el tramo. Una pérdida continua
no representa eso, y un modelo optimizado para MAE no es el óptimo para la
liquidación. Esto confirma, con regulación en la mano, la dependencia **D3** del
registro de Fase 1.

**Pero nuestra planta no es este caso.** El umbral de despacho central está
muy por encima de 500 kW —se discute bajarlo a 5 MW— así que una planta de
medio megavatio no entra por ningún lado.

### 2. Generador NO despachado centralmente

Para estas plantas, la Obligación Diaria de Energía Firme Ajustada **es igual a
su generación ideal del día**, y el factor de ajuste siempre vale uno. Es decir:
no hay exposición a desviaciones por esa vía.

Su exposición al error es **comercial, no regulatoria**: la diferencia entre lo
que vendió en contratos y lo que generó se liquida en bolsa. Si generó de menos,
compra en bolsa para cumplir; si generó de más, vende el sobrante en bolsa.

**Aquí sí hay costo unitario, y es el diferencial entre el precio de contrato y
el precio de bolsa en la hora del error.** Ese diferencial es el dato duro de
esta fase.

### 3. Usuario no regulado

Industria y comercio con contrato bilateral. Si tiene generación propia, el
error de pronóstico le mueve la cantidad que debe comprar, y el desajuste se
liquida contra bolsa igual que arriba.

**Advertencia que ya estaba en el registro (D6) y que esto confirma:** lo que se
liquida es la **exportación o el faltante**, no la generación bruta. El
autoconsumo industrial es un proceso estocástico distinto, no meteorológico.
Pronosticar generación bruta no pronostica la cantidad que se liquida.

---

## El dato duro: el diferencial bolsa-contrato en 2026

Fuente: informes mensuales de XM sobre el Mercado de Energía Mayorista.

| Mes 2026 | Bolsa (COP/kWh) | Contratos no regulado (COP/kWh) | Diferencial |
|---|---|---|---|
| Enero | 213,0 | 293,0 | −80 |
| Febrero | 124,3 | 284,5 | −160 |
| Marzo | 223,8 | 293,4 | −70 |
| Abril | 280,2 | 304,5 | −24 |
| Junio | 562,1 | 311,8 | **+250** |
| Julio | 797,7 | ~330 | **+468** |
| Agosto | 946,6 | 329,7 | **+617** |

**El precio de bolsa se multiplicó por 7,6 entre febrero y agosto de 2026**
—de 124,3 a 946,6 COP/kWh—, mientras los contratos se mantuvieron estables
entre 284 y 332. XM atribuye el alza de agosto a mayor demanda por temperaturas
altas asociadas al Fenómeno de El Niño y a vencimientos de contratos.

### Lo que esto significa para valorar el error

**El costo unitario del error no es un número: es una distribución con cola.**
En febrero, equivocarse costaba poco y a favor; en agosto, el mismo error en
kWh costaba casi ocho veces más. Cualquier cálculo de valor anual hecho con un
precio promedio **subestima el riesgo**, porque el error y el precio alto
pueden coincidir: los días de El Niño son días despejados, y un error de
pronóstico en un día despejado es precisamente el que más energía mueve.

**Propuesta de método, para cuando haya cliente:** no multiplicar MAE anual por
un precio promedio. Simular la liquidación hora a hora con la serie real de
precios, y reportar el valor como distribución —mediana y percentil 95—, no
como promedio. Esa simulación es el entregable que falta y que sigue bloqueado
por D2 y D6.

---

## Qué queda verificado, supuesto y pendiente

**Verificado con fuente:**
- Límite AGPE = 1 MW; una planta de 500 kWp es AGPE.
- La liquidación del AGPE es por período de facturación, con excedentes
  partidos en dos categorías; se tratan como reducción de demanda.
- Para plantas no despachadas centralmente, la obligación ajustada iguala la
  generación ideal y el factor de ajuste vale uno.
- Precios de bolsa y de contratos mes a mes de 2026 según XM.

**Supuesto, por declarar:**
- Que la planta de referencia entrega excedentes. Si opera con limitador de
  potencia y cero inyección, el error de pronóstico vale aún menos.
- Que el diferencial bolsa-contrato es el costo unitario relevante para los
  roles 2 y 3. Depende del contrato concreto: un contrato pay-as-produced
  traslada el riesgo distinto que uno de cantidad fija.

**Pendiente, y no se puede resolver sin cliente:**
- Cuál es el rol exacto y el contrato exacto.
- La estructura de penalidad del contrato bilateral, que puede ser más
  exigente que la regulatoria. **Un contrato privado puede penalizar
  desviaciones aunque la regulación no lo haga**, y eso cambiaría el veredicto
  para un AGPE.
- Si existe valor operativo —baterías, cargas desplazables— que no pasa por el
  mercado.

---

## Veredicto preliminar, por rol

| Rol | ¿El error horario tiene precio? | Criterio |
|---|---|---|
| AGPE (≤ 1 MW) — **nuestra planta** | **No**, salvo contrato privado que lo imponga | M10 → **DETENTE** sobre la valoración de mercado |
| Generador no despachado centralmente | Sí: diferencial bolsa-contrato | SIGUE, con simulación pendiente |
| Generador variable despachado centralmente | Sí, con banda muerta y escalones (en proyecto) | SIGUE, y **la métrica no es MAE** |
| Usuario no regulado | Sí, sobre la cantidad liquidada, que no es la generación bruta | SIGUE, condicionado a D6 |

**El hallazgo más incómodo y el más útil:** el proyecto, tal como está
planteado sobre una planta de 500 kWp, apunta a un rol que no paga por
equivocarse. Eso no invalida el banco de pruebas ni el método —son
independientes del rol—, pero sí obliga a replantear a quién se le vende. El
cliente que paga por este pronóstico es un generador no despachado centralmente
o un usuario no regulado con contrato de cantidad fija, no un autogenerador
pequeño.
