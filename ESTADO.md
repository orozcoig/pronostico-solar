# Estado y punto de reanudación

Octubre de 2026. **Sin cliente.** El proyecto queda detenido a propósito, no
por falta de trabajo técnico: por el criterio M3, que exige cerrar la Fase 1
—hora de emisión, horizonte y estructura de penalidad— antes de poder definir
qué es una mejora.

---

## Lo que está terminado y es entregable hoy

| | |
|---|---|
| Banco sintético | 10 fallas en 3 capas, 11/11 escenarios, control negativo limpio |
| Curva de potencia diagnóstica | 9 de 10 fallas con 6 meses; suciedad necesita 24 |
| Contrato de datos | 2 implementaciones probadas: sintética y CSV, mismo veredicto |
| Líneas base y vara | 3 referencias; diferencias pareadas con bootstrap de bloques |
| Modelo | Árboles con pérdida cuantílica; supera la mejor línea base por 5,06 kW contra vara de 1,99 |
| Techo alcanzable | 6,1 kW: **el 87 % del error es del proveedor meteorológico** |
| Qué compra cada técnica | Ensamble de 5 miembros: −10,26 kW. Post-proceso del NWP: nada |
| Criterios de muerte | 11 criterios evaluables, fijados en pruebas |
| Infraestructura | 21 módulos, 21 pruebas, CI con 4 jobs, Colab de 16 celdas |

**Nada de esto depende del cliente.** La estructura es independiente del rol;
los números son del sitio sintético y no se transfieren.

---

## Las tres preguntas de la primera reunión

En este orden. Las dos primeras pueden terminar la conversación.

**1. ¿Qué rol regulatorio tiene y cómo se liquida?**
Si es autogenerador de hasta 1 MW, su error horario no tiene precio: se liquida
por período de facturación. Ahí no hay motor de pronóstico que vender, salvo
que su contrato privado imponga una penalidad que la regulación no impone, o
que haya valor operativo (baterías, cargas desplazables). Ver
`FASE2_COSTO_DEL_ERROR.md`. Evaluar con `criterios.m11_rol_expuesto_al_error`.

**2. ¿Tiene medición horaria con doce meses, y archivo de las corridas pasadas
de su proveedor meteorológico?**
Sin lo primero no es un proyecto de pronóstico. Sin lo segundo cambia el
cronograma: hay que acumular archivo, y entrenar con reanálisis en su lugar es
la fuga más cara de este proyecto. Evaluar con `m1_historia_minima` y
`m2_archivo_de_pronostico`.

**3. ¿A qué hora hay que emitir el pronóstico, para qué trámite, y cuánto
cuesta pasarse contra quedarse corto?**
El horizonte lo impone el trámite. Si la penalidad es asimétrica o escalonada,
la métrica no es MAE y la función de pérdida cambia. Es la Fase 1 completa.

---

## Los tres números que van en esa reunión, antes de la entrega

1. **El error relativo en un sitio único será mucho mayor que a escala
   nacional.** Una nube mueve el cien por ciento de una planta. En el banco, la
   banda honesta de incertidumbre a día adelante mide el 61 % de la capacidad.
2. **Buena parte del error no es comprable: viene del proveedor
   meteorológico.** En el banco, el 87 %. El experimento que lo mide no
   requiere construir ningún modelo y cabe entero en la Etapa 1.
3. **Pedirle el ensamble al proveedor compra más que todo el trabajo de
   modelado junto.** Medido: −10,26 kW con cinco miembros, contra −5,06 kW del
   modelo sobre la mejor línea base.

---

## Lo que falta, y por qué no se hizo

**Bloqueado por el cliente, correctamente:**
- Simulación de liquidación en pesos y valor anual (depende de la penalidad y
  de qué cantidad se liquida).
- Definición de la Etapa 3: hora de entrega, formato, modos de falla.
- `FuenteSCADA`: la tercera implementación del contrato solo se escribe contra
  un historiador real.

**Limitaciones medidas y documentadas, no tapadas:**
- Dos puntos ciegos del diagnóstico de modelo: pérdida desalineada y features
  faltantes. Cubiertos por el criterio M8, que convierte un silencio del agente
  sobre esos temas en REPLANTEA y no en "no hay problema".
- El banco no puede evaluar si la dispersión del ensamble mejora la
  calibración: sus miembros difieren solo por el sorteo de los mismos
  mecanismos (R² = 0,87 contra el campo medio). Un ensamble real sí lleva
  información independiente.
- El piso del error no está establecido: solo se sabe que está por debajo de
  36,4 kW, y cada miembro adicional sigue superando la vara hasta nueve.

**Pendiente menor antes de publicar el repositorio:**
- Reemplazar la URL de ejemplo en `README.md` y en la primera celda del Colab.
  Ver `CONFIG.md`.

---

## Una nota de método

Esta sesión produjo catorce correcciones del mismo tipo: una medición
interpretada sobre una referencia que una etapa anterior sabía contaminada. Doce
fueron de datos y dos de método propio. De ahí salió el orden de diagnóstico
que está codificado en `agente` y documentado en `CLAUDE.md`, y que no es
preferencia sino dependencia medida.

Y cuatro veces escribir la expectativa **antes** de medir convirtió un
resultado confuso en un hallazgo: el post-proceso que no servía, el ensamble
que rompió un piso que yo había declarado irreducible, la regularización que
empeoró, la dispersión que no aportaba. En los cuatro casos, medir primero
habría llevado a ajustar parámetros en vez de preguntar por qué.
