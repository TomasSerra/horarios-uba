"""Decisión de si una corrida del job de vacantes puede escribir.

El job horario toca **una sola columna** (`cursos.vacantes`) y sólo sobre la
intersección (fuente ∩ DB): no borra, no inserta y no toca vigencia. Así, todo
modo de falla degrada a "las vacantes quedan stale", que es exactamente el
status quo entre corridas del scraper diario.

Lo que estas guardas protegen es el caso que la regla aditiva no cubre: que la
fuente devuelva datos **plausibles pero equivocados**. Un corrimiento de columna
en el HTML, un WAF que responde 200 con una página de error, o un flip de
cuatrimestre escriben números que parecen cupos y no lo son. Ahí no alcanza con
"no borrar nada": hay que no escribir.

Lógica pura y sin I/O a propósito, igual que `vigencia.evaluar_sweep`: es donde
vive el riesgo real y se testea sola.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# --- Umbrales -----------------------------------------------------------------
# Todos overrideables por env para poder apretarlos sin deploy. Los defaults
# están calibrados sobre los números reales de la DB: 219 cátedras en el índice,
# ~2.370 comisiones principales vigentes.

# Menos cátedras que esto en el índice = la fuente está a medio cargar (68% de 219).
MIN_CATEDRAS = int(os.environ.get("VACANTES_MIN_CATEDRAS", "150"))

# Un bloqueo por WAF lleva `paginas_ok` a ~0. El 15% de tolerancia cubre un
# puñado de páginas genuinamente flaky sin dejar pasar un bloqueo.
MIN_PAGINAS_OK_RATIO = float(os.environ.get("VACANTES_MIN_PAGINAS_OK_RATIO", "0.85"))

# Piso de "esto ya no es la misma página". Deliberadamente flojo: el detector
# primario de corrimiento de columna es la validación de headers, que es
# determinista y no tiene falsos positivos.
MIN_CON_VALOR_RATIO = float(os.environ.get("VACANTES_MIN_CON_VALOR_RATIO", "0.5"))

# Fuente y DB salen de las **mismas** 219 cátedras, así que la cobertura normal
# es ~100%. Por debajo de esto divergieron estructuralmente y actualizar la
# intersección ya no es semánticamente correcto.
MIN_MATCHED_RATIO = float(os.environ.get("VACANTES_MIN_MATCHED_RATIO", "0.7"))

# Comisiones nuevas a mitad de cuatrimestre son unidades. Cientos de golpe =
# corrida diaria rota o cuatrimestre nuevo.
MAX_SIN_MATCH_RATIO = float(os.environ.get("VACANTES_MAX_SIN_MATCH_RATIO", "0.15"))

# El breaker más valioso: es la última línea antes del write. En inscripciones
# reales el cambio hora a hora son decenas de 2.370, nunca mayoría. Es la firma
# de un parse de columna equivocada que dio ints plausibles. Generoso a propósito
# para la primera semana; apretar a ~0.35 después de observar una hora real.
MAX_CAMBIOS_RATIO = float(os.environ.get("VACANTES_MAX_CAMBIOS_RATIO", "0.6"))

# La fila individual fuera de rango se descarta siempre; más del 1% (24 filas)
# ya es sistemático, no un typo de la fuente.
MAX_FUERA_DE_RANGO_RATIO = float(
    os.environ.get("VACANTES_MAX_FUERA_DE_RANGO_RATIO", "0.01")
)

# Piso para que los breakers de ratio tengan sentido: con 1 comisión matcheada,
# una sola que cambie es el 100% y abortaría siempre. La corrida real trabaja
# sobre ~2.370, así que esto sólo afecta a las corridas con `--limit`.
MIN_MUESTRA_PARA_RATIO = int(os.environ.get("VACANTES_MIN_MUESTRA_PARA_RATIO", "50"))

# Un fallo HTTP aislado es normal; 10 seguidos es un bloqueo. Cortar ahí es
# cortesía con la fuente y no gastar 5 min de runner contra un WAF.
MAX_FALLOS_CONSECUTIVOS = int(os.environ.get("VACANTES_MAX_FALLOS_CONSECUTIVOS", "10"))

# Rango aceptable para un valor de vacantes. Los negativos existen (sobrecupo) y
# el resto del sistema los trata como "sin cupo" (`solo_con_cupos` pide > 0).
#
# El techo tiene que dejar pasar las comisiones asincrónicas por campus virtual,
# que son legítimamente enormes: el máximo observado son las 850 de Idioma Inglés
# Módulo II (cátedra 854). 1500 les da margen de crecimiento y sigue descartando
# un año ("2025") si el parse cae en otra columna, que es de lo que protege.
VACANTES_MIN = -999
VACANTES_MAX = 1500


@dataclass
class MetricasVacantes:
    """Todo lo que la corrida observó. La llena el job; las guardas sólo la leen."""

    # Fetch
    paginas_totales: int = 0
    paginas_ok: int = 0
    paginas_http_error: int = 0
    paginas_sin_parse: int = 0
    paginas_shape_mala: int = 0
    paginas_catedra_mismatch: int = 0
    fallos_consecutivos: int = 0
    corte_por_fallos: bool = False

    # Claves de la fuente
    claves_fuente: int = 0
    con_valor: int = 0
    sin_valor: int = 0
    fuera_de_rango: int = 0
    duplicadas_en_pagina: int = 0
    # Las que llegaron al diff: `claves_fuente` menos las de cátedras salteadas
    # por cuatrimestre. Es el denominador correcto para los ratios post-SELECT.
    claves_consideradas: int = 0

    # DB y diff
    claves_db: int = 0
    descartadas_no_vigente: int = 0
    en_materia_congelada: int = 0
    saltadas_por_cuatrimestre: int = 0
    matched: int = 0
    sin_match_fuente: int = 0
    sin_ver_db: int = 0
    cambios: int = 0
    nuevos_null_en_db: int = 0

    # Observado, para el reporte
    valores_vistos: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionVacantes:
    escribir: bool
    motivo: str


def evaluar_fetch(
    m: MetricasVacantes, forzar: bool = False
) -> DecisionVacantes:
    """¿Vale la pena abrir la conexión con lo que trajo el fetch?

    Corre **antes** de tocar la DB: un abort acá no despierta el compute de Neon.
    """
    if m.paginas_totales == 0:
        # Ni con --force. Un índice vacío no es una oferta que se recortó, es la
        # fuente caída o la URL que dejó de servir datos. Mismo criterio que el
        # sweep.
        return DecisionVacantes(
            False, "el índice vino vacío (la fuente puede estar caída)"
        )

    if m.corte_por_fallos:
        return DecisionVacantes(
            False,
            f"corte temprano: {m.fallos_consecutivos} fallos HTTP consecutivos "
            f"(máximo {MAX_FALLOS_CONSECUTIVOS}). La fuente puede estar "
            f"bloqueando o caída",
        )

    if m.paginas_totales < MIN_CATEDRAS and not forzar:
        return DecisionVacantes(
            False,
            f"el índice trae {m.paginas_totales} cátedras, menos del mínimo "
            f"{MIN_CATEDRAS}: puede estar a medio cargar",
        )

    minimo_ok = m.paginas_totales * MIN_PAGINAS_OK_RATIO
    if m.paginas_ok < minimo_ok and not forzar:
        return DecisionVacantes(
            False,
            f"sólo {m.paginas_ok} de {m.paginas_totales} páginas parsearon OK "
            f"(mínimo {minimo_ok:.0f}). "
            f"http_error={m.paginas_http_error} sin_parse={m.paginas_sin_parse} "
            f"shape_mala={m.paginas_shape_mala} "
            f"catedra_mismatch={m.paginas_catedra_mismatch}",
        )

    if m.claves_fuente == 0:
        return DecisionVacantes(
            False, "ninguna comisión con código salió del fetch: no hay nada que escribir"
        )

    max_fuera = m.claves_fuente * MAX_FUERA_DE_RANGO_RATIO
    if m.fuera_de_rango > max_fuera and not forzar:
        return DecisionVacantes(
            False,
            f"{m.fuera_de_rango} de {m.claves_fuente} valores fuera del rango "
            f"[{VACANTES_MIN}, {VACANTES_MAX}] (máximo {max_fuera:.0f}): el parse "
            f"puede estar leyendo otra columna",
        )

    minimo_con_valor = m.claves_fuente * MIN_CON_VALOR_RATIO
    if m.con_valor < minimo_con_valor and not forzar:
        return DecisionVacantes(
            False,
            f"sólo {m.con_valor} de {m.claves_fuente} comisiones traen un número "
            f"de vacantes (mínimo {minimo_con_valor:.0f}): la página cambió",
        )

    return DecisionVacantes(
        True,
        f"fetch OK: {m.paginas_ok}/{m.paginas_totales} páginas, "
        f"{m.con_valor}/{m.claves_fuente} comisiones con valor",
    )


def evaluar_actualizacion(
    m: MetricasVacantes, forzar: bool = False
) -> DecisionVacantes:
    """¿Se puede escribir el diff que salió de comparar contra la DB?

    Corre **dentro** de la transacción, después del SELECT: un abort acá hace
    rollback y no deja escritura parcial.
    """
    if m.claves_db == 0:
        # Ni con --force: o los predicados del SELECT están mal, o no hay oferta
        # vigente. En los dos casos escribir no puede ser lo correcto.
        return DecisionVacantes(
            False,
            "el SELECT no devolvió ninguna comisión vigente: revisar el scope "
            "de la query o la vigencia de la oferta",
        )

    minimo_matched = m.claves_db * MIN_MATCHED_RATIO
    if m.matched < minimo_matched and not forzar:
        return DecisionVacantes(
            False,
            f"sólo {m.matched} de {m.claves_db} comisiones de la DB aparecieron "
            f"en la fuente (mínimo {minimo_matched:.0f}): fuente y DB divergieron",
        )

    max_sin_match = m.claves_consideradas * MAX_SIN_MATCH_RATIO
    if (
        m.claves_consideradas >= MIN_MUESTRA_PARA_RATIO
        and m.sin_match_fuente > max_sin_match
        and not forzar
    ):
        return DecisionVacantes(
            False,
            f"{m.sin_match_fuente} de {m.claves_consideradas} comisiones de la "
            f"fuente no existen en la DB (máximo {max_sin_match:.0f}): la corrida "
            f"diaria puede estar rota o cambió el cuatrimestre",
        )

    max_cambios = m.matched * MAX_CAMBIOS_RATIO
    if (
        m.matched >= MIN_MUESTRA_PARA_RATIO
        and m.cambios > max_cambios
        and not forzar
    ):
        return DecisionVacantes(
            False,
            f"cambiaron {m.cambios} de {m.matched} comisiones "
            f"(máximo {max_cambios:.0f}): demasiado para una hora, el parse puede "
            f"estar leyendo otra columna",
        )

    if not m.matched:
        # Sólo alcanzable con `forzar`: sin él, el mínimo de cobertura ya cortó.
        return DecisionVacantes(True, "0 comisiones matcheadas: no hay nada que escribir")

    return DecisionVacantes(
        True,
        f"{m.cambios} cambios sobre {m.matched} comisiones matcheadas "
        f"({m.cambios / m.matched:.1%}, máximo {MAX_CAMBIOS_RATIO:.0%})",
    )


def verificar_rowcount(rowcount: int, esperado: int) -> str | None:
    """Valida el `rowcount` del UPDATE contra el largo del payload.

    Con `tipo='comision' AND parte_de_id IS NULL` la clave
    `(catedra_id, codigo)` es única, así que `rowcount == esperado` es exacto.
    Este chequeo caza en un tiro tres cosas distintas: que la clave dejó de ser
    única, que otro proceso borró filas en el medio, y que el scope del UPDATE
    no coincide con el del SELECT.

    Devuelve un mensaje de warning si la diferencia es tolerable, o `None` si
    está perfecto. Raisea si no es tolerable.
    """
    if rowcount == esperado:
        return None

    if rowcount > esperado:
        raise RuntimeError(
            f"el UPDATE tocó {rowcount} filas para un payload de {esperado}: la "
            f"clave (catedra_id, codigo) dejó de ser única entre comisiones "
            f"principales. No se commitea nada"
        )

    if rowcount < esperado * 0.9:
        raise RuntimeError(
            f"el UPDATE tocó sólo {rowcount} de {esperado} filas esperadas: el "
            f"scope del UPDATE no coincide con el del SELECT. No se commitea nada"
        )

    # Faltante chico: alguien más escribió el mismo valor entre el SELECT y el
    # UPDATE (el `IS DISTINCT FROM` lo filtró). Benigno.
    return (
        f"el UPDATE tocó {rowcount} de {esperado} filas: {esperado - rowcount} "
        f"ya tenían el valor nuevo (write concurrente)"
    )
