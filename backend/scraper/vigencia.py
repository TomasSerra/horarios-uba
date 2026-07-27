"""Decisión de si una corrida del scraper puede dar de baja cátedras.

El sweep apaga (`vigente = FALSE`) las cátedras que ya no figuran en el índice de
la fuente. Es la única operación del scraper que saca oferta de circulación, así
que va detrás de guardas: entre el 1er y el 2do cuatrimestre la fuente deja de
publicar datos por un tiempo, y una corrida contra un índice vacío o a medio
cargar no puede vaciar la app.

Lógica pura y sin I/O a propósito: es donde vive el riesgo real y se testea sola.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Si el índice trae menos de esta fracción de las cátedras vigentes actuales,
# asumimos que la fuente está a medio cargar y no barremos.
MIN_SWEEP_RATIO = float(os.environ.get("SCRAPER_MIN_SWEEP_RATIO", "0.5"))


@dataclass(frozen=True)
class DecisionSweep:
    barrer: bool
    motivo: str


def evaluar_sweep(
    descubiertas: int,
    vigentes_actuales: int,
    forzar: bool = False,
    min_ratio: float = MIN_SWEEP_RATIO,
) -> DecisionSweep:
    """¿Puede esta corrida dar de baja las cátedras que no vio?

    `descubiertas` es el tamaño del índice de esta corrida y `vigentes_actuales`
    cuántas cátedras hay hoy marcadas como vigentes en la DB.
    """
    if descubiertas == 0:
        # Ni con --force-sweep: barrer con el índice vacío daría de baja el 100%
        # de la oferta, y eso nunca es lo que se quiso pedir. Es exactamente el
        # caso de la fuente caída o de la URL que deja de servir datos.
        return DecisionSweep(
            False,
            "el índice vino vacío: no se da de baja nada (la fuente puede estar caída)",
        )

    if vigentes_actuales == 0:
        return DecisionSweep(
            True, "no hay cátedras vigentes en la DB: no hay nada que dar de baja"
        )

    minimo = vigentes_actuales * min_ratio
    if descubiertas >= minimo:
        return DecisionSweep(
            True,
            f"el índice trae {descubiertas} de {vigentes_actuales} vigentes "
            f"(mínimo {minimo:.0f})",
        )

    if forzar:
        return DecisionSweep(
            True,
            f"--force-sweep: el índice trae {descubiertas} de {vigentes_actuales} "
            f"vigentes, por debajo del mínimo {minimo:.0f}",
        )

    return DecisionSweep(
        False,
        f"el índice trae {descubiertas}, menos del {min_ratio:.0%} de las "
        f"{vigentes_actuales} vigentes actuales (mínimo {minimo:.0f}). "
        f"Si el cambio es real, re-correr con --force-sweep",
    )
