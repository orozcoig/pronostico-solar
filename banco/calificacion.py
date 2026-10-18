"""Criterio de aprobación 3.4 y control negativo 3.5, como prueba automática.

**La métrica de esta fase NO es el error de pronóstico: es el acierto
diagnóstico.** Un agente que baja el MAE sin identificar la causa no aprueba.

Un escenario se aprueba si se cumplen las cuatro condiciones:

  1. ACIERTO      — nombró la falla inyectada.
  2. MEDICIÓN     — la nombró a partir del detector que el manifiesto declara.
  3. CONTENCIÓN   — no inventó fallas que no se inyectaron.
  4. RECHAZO      — enumeró las técnicas que NO aplican.

El control negativo (3.5) es el mismo criterio con cero fallas inyectadas: la
única salida aprobatoria es la lista vacía.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agente import Hallazgo


@dataclass
class Calificacion:
    escenario: str
    esperadas: set
    encontradas: set
    aciertos: set
    faltantes: set
    falsos_positivos: set
    detector_correcto: dict
    rechazo_declarado: dict

    @property
    def aprueba(self) -> bool:
        return (
            not self.faltantes
            and not self.falsos_positivos
            and all(self.detector_correcto.values())
            and all(self.rechazo_declarado.values())
        )

    def linea(self) -> str:
        marca = "APRUEBA" if self.aprueba else "REPRUEBA"
        det = ("-" if not self.aciertos
               else ("si" if all(self.detector_correcto.values()) else "NO"))
        return (
            f"{self.escenario:<26}{marca:<10}"
            f"acierto {len(self.aciertos)}/{len(self.esperadas)}  "
            f"falsos+ {len(self.falsos_positivos)}  "
            f"detector {det}"
        )

    def motivo(self) -> str:
        if self.aprueba:
            return ""
        partes = []
        if self.faltantes:
            partes.append(f"no detectó {sorted(self.faltantes)}")
        if self.falsos_positivos:
            partes.append(f"inventó {sorted(self.falsos_positivos)}")
        malos = [k for k, v in self.detector_correcto.items() if not v]
        if malos:
            partes.append(f"detector equivocado en {malos}")
        sin = [k for k, v in self.rechazo_declarado.items() if not v]
        if sin:
            partes.append(f"no declaró qué NO aplicar en {sin}")
        return "; ".join(partes)


def calificar(nombre: str, hallazgos: list[Hallazgo], manifiesto: dict) -> Calificacion:
    esperadas = {f["falla"] for f in manifiesto["fallas"]}
    detector_esperado = {f["falla"]: f.get("detector_esperado") for f in manifiesto["fallas"]}
    encontradas = {h.falla for h in hallazgos}
    por_falla = {h.falla: h for h in hallazgos}

    aciertos = esperadas & encontradas
    return Calificacion(
        escenario=nombre,
        esperadas=esperadas,
        encontradas=encontradas,
        aciertos=aciertos,
        faltantes=esperadas - encontradas,
        falsos_positivos=encontradas - esperadas,
        detector_correcto={
            f: por_falla[f].detector == detector_esperado[f] for f in aciertos
        },
        # Enumerar lo que NO aplica es parte del criterio: un agente que solo
        # propone técnicas, sin descartar, no demuestra haber diagnosticado.
        rechazo_declarado={f: bool(por_falla[f].tecnicas_no) for f in aciertos},
    )


def tabla(calificaciones: list[Calificacion]) -> str:
    lineas = [c.linea() + (f"   <- {c.motivo()}" if not c.aprueba else "")
              for c in calificaciones]
    n_ok = sum(c.aprueba for c in calificaciones)
    lineas.append(f"\n{n_ok}/{len(calificaciones)} escenarios aprobados")
    return "\n".join(lineas)
