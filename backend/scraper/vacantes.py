"""Job de alta frecuencia que actualiza **sólo** `cursos.vacantes`.

Corre cada hora en horario de vigilia (ver `.github/workflows/vacantes.yml`), en
paralelo al scraper diario, que sigue siendo el dueño de todo lo demás:
horarios, aulas, profesores, comisiones y vigencia.

Por qué existe separado en vez de subirle la frecuencia a `scraper.main`:
`replace_cursos` borra y re-inserta todos los cursos de cada cátedra, o sea 100%
de turnover de `cursos` y `comision_obliga` por corrida, y además puede disparar
el sweep de vigencia. Nada de eso es aceptable 17 veces por día.

Diseño:

1. Se fetchean las 219 páginas **sin abrir la DB**.
2. Recién al final, una conexión y una transacción: SELECT del estado actual,
   diff en Python, guardas, un UPDATE batcheado.

El paso 2 es lo que hace que la DB esté despierta segundos en vez de minutos —
pero el motivo principal de batchear es de seguridad: todos los circuit breakers
se evalúan antes del write, y la ventana de locks es de milisegundos.

Invariante: **se escribe sólo sobre la intersección (fuente ∩ DB), y sólo
valores `int` efectivamente vistos.** Nunca NULL, nunca 0 por ausencia, nunca un
DELETE o un INSERT, nunca otra columna. Todo modo de falla degrada a "las
vacantes quedan stale", que es el status quo entre corridas diarias.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .config import CATEDRA_URL, DELAY_SECONDS
from .db import get_conn
from .discover import IndexEntry, discover_catedras
from .http import fetch
from .parse import parse_catedra_page
from .vacantes_guardas import (
    MAX_FALLOS_CONSECUTIVOS,
    MIN_CATEDRAS,
    VACANTES_MAX,
    VACANTES_MIN,
    MetricasVacantes,
    evaluar_actualizacion,
    evaluar_fetch,
    verificar_rowcount,
)

# El scope: comisiones principales. Las partes no traen cupo propio y comparten
# el `codigo` de su principal, así que sin `parte_de_id IS NULL` el cupo del
# padre se copiaría a las ~521 partes. `vigente` y `cuatrimestre` viajan para
# filtrar en Python (así se puede contar cuántas claves se descartan y por qué);
# `oferta_congelada` es sólo para el reporte.
SELECT_ESTADO = """
    SELECT c.catedra_id, c.codigo, c.vacantes,
           ca.vigente, ca.cuatrimestre, m.oferta_congelada
      FROM cursos c
      JOIN catedras ca ON ca.id = c.catedra_id
      JOIN materias m  ON m.codigo = ca.materia_codigo
     WHERE c.tipo = 'comision'
       AND c.parte_de_id IS NULL
"""

# `unnest` en vez de VALUES o executemany: el texto del SQL es constante (nada
# de armarlo por concatenación), son 3 parámetros de array y psycopg adapta
# list[int]/list[str] nativo. Mismo espíritu que el `= ANY(%(ids)s)` de db.py.
#
# `v.vacantes IS NOT NULL` es imprescindible y no cosmético: unnest con arrays de
# largo distinto **rellena con NULL**, y la columna es nullable sin CHECK.
# `IS DISTINCT FROM` deja el rowcount exactamente asertable y evita generar WAL
# por filas que ya tenían el valor.
UPDATE_VACANTES = """
    UPDATE cursos c
       SET vacantes = v.vacantes
      FROM unnest(
             %(catedras)s::int[],
             %(codigos)s::text[],
             %(vacantes)s::int[]
           ) AS v(catedra_id, codigo, vacantes)
     WHERE c.catedra_id   = v.catedra_id
       AND c.codigo       = v.codigo
       AND c.tipo         = 'comision'
       AND c.parte_de_id IS NULL
       AND v.vacantes    IS NOT NULL
       AND c.vacantes    IS DISTINCT FROM v.vacantes
"""

# Índice de la columna `Vac.` en las filas de la tabla de comisiones. Tiene que
# coincidir con el `cells[6]` de `parse._parse_rows`, que lee posicionalmente y
# sin validar headers: si la fuente inserta una columna, ese parse sigue
# devolviendo números plausibles de otra celda. Esta validación es el detector
# primario de ese caso (determinista, sin falsos positivos).
COL_VACANTES = 6
HEADER_VACANTES = "vac"


@dataclass
class PaginaVacantes:
    catedra_id: int
    cuatrimestre: str | None
    # codigo de comisión -> vacantes. None = la fuente no publicó un número.
    vacantes: dict[str, int | None] = field(default_factory=dict)


def validar_headers_comisiones(html: str) -> str:
    """`ok` | `shape_mala` | `sin_tabla`.

    Confirma que en la tabla de Comisiones el header de la posición que
    `_parse_rows` lee como vacantes siga siendo `Vac.`.
    """
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table", class_="table_tabs"):
        ths = table.find_all("th")
        if not ths:
            continue
        etiqueta = ths[0].get_text(strip=True).replace("\xa0", "").strip()
        if etiqueta != "Comisiones":
            continue
        if len(ths) <= COL_VACANTES:
            return "shape_mala"
        header = (
            ths[COL_VACANTES].get_text(strip=True).replace("\xa0", "").strip().lower()
        )
        return "ok" if header.startswith(HEADER_VACANTES) else "shape_mala"
    return "sin_tabla"


def recolectar(
    entries: list[IndexEntry],
    m: MetricasVacantes,
    *,
    fetch_fn: Callable[..., str] = fetch,
    delay: float = DELAY_SECONDS,
    verbose: bool = False,
) -> dict[int, PaginaVacantes]:
    """Baja y parsea las páginas de cátedra. No toca la DB.

    `fetch_fn` es inyectable para poder testear el loop sin red.
    """
    m.paginas_totales = len(entries)
    paginas: dict[int, PaginaVacantes] = {}
    total = len(entries)

    for i, entry in enumerate(entries, start=1):
        try:
            html = fetch_fn(CATEDRA_URL, params={"catedra": entry.catedra_id})
        except Exception as exc:
            m.paginas_http_error += 1
            m.fallos_consecutivos += 1
            print(
                f"VACANTES-WARN: [{i}/{total}] catedra={entry.catedra_id} "
                f"fallo HTTP {exc!r}"
            )
            if m.fallos_consecutivos >= MAX_FALLOS_CONSECUTIVOS:
                # Cortar acá es cortesía con la fuente (es un PHP de la facultad)
                # y no gastar el resto del runner contra un WAF.
                m.corte_por_fallos = True
                return paginas
            if i < total:
                time.sleep(delay)
            continue

        m.fallos_consecutivos = 0
        detalle = parse_catedra_page(html)

        if detalle is None:
            # 200 con HTML que no matchea el header: página de error, WAF o
            # cambio de estructura.
            m.paginas_sin_parse += 1
        elif detalle.catedra_id != entry.catedra_id:
            # La fuente devolvió otra cátedra (redirect, sesión cruzada).
            m.paginas_catedra_mismatch += 1
            print(
                f"VACANTES-WARN: catedra={entry.catedra_id} devolvió "
                f"catedra={detalle.catedra_id}, descartada"
            )
        elif validar_headers_comisiones(html) == "shape_mala":
            m.paginas_shape_mala += 1
            print(
                f"VACANTES-WARN: catedra={entry.catedra_id} la columna "
                f"{COL_VACANTES} de Comisiones ya no es 'Vac.', descartada"
            )
        else:
            m.paginas_ok += 1
            paginas[entry.catedra_id] = _pagina_desde_detalle(detalle, m, verbose)

        if i < total:
            time.sleep(delay)

    return paginas


def _pagina_desde_detalle(detalle, m: MetricasVacantes, verbose: bool) -> PaginaVacantes:
    """Extrae `codigo -> vacantes` de las comisiones principales de una página.

    Sólo top-level: las partes viven en `Curso.partes` y no tienen cupo propio.
    """
    pagina = PaginaVacantes(
        catedra_id=detalle.catedra_id, cuatrimestre=detalle.cuatrimestre
    )
    duplicados: set[str] = set()

    for curso in detalle.cursos:
        if curso.tipo != "comision" or not curso.codigo:
            continue
        if curso.codigo in pagina.vacantes:
            # Dos comisiones con el mismo código en la misma página (typo de la
            # fuente): no hay forma de saber cuál fila de la DB es cuál, así que
            # se descartan las dos.
            duplicados.add(curso.codigo)
            continue
        pagina.vacantes[curso.codigo] = curso.vacantes

    for codigo in duplicados:
        del pagina.vacantes[codigo]
        m.duplicadas_en_pagina += 1
        print(
            f"VACANTES-WARN: catedra={detalle.catedra_id} comision={codigo} "
            f"aparece duplicada, se descarta"
        )

    for codigo, valor in list(pagina.vacantes.items()):
        m.claves_fuente += 1
        if valor is None:
            m.sin_valor += 1
        elif not VACANTES_MIN <= valor <= VACANTES_MAX:
            # Un año ("2025") o un número de aula: el parse cayó en otra columna.
            m.fuera_de_rango += 1
            pagina.vacantes[codigo] = None
            print(
                f"VACANTES-WARN: catedra={detalle.catedra_id} comision={codigo} "
                f"vacantes={valor} fuera de rango, se descarta"
            )
        else:
            m.con_valor += 1
            m.valores_vistos.append(valor)

    if verbose:
        print(
            f"  catedra={detalle.catedra_id}: {len(pagina.vacantes)} comisiones "
            f"({detalle.cuatrimestre})"
        )
    return pagina


def calcular_payload(
    paginas: dict[int, PaginaVacantes],
    filas_db: list[tuple],
    m: MetricasVacantes,
) -> list[tuple[int, str, int]]:
    """Diff entre lo que trajo la fuente y lo que hay en la DB.

    `claves_db` se acota a las cátedras que **se leyeron con éxito**: así los
    ratios de cobertura miden lo que tienen que medir y una página que falló no
    arrastra las métricas (ya la contó el breaker de `paginas_ok`). Como efecto
    lateral, `--limit` funciona sin ningún caso especial.
    """
    # Cuatrimestre que la DB tiene por cátedra. Todas las filas de una cátedra
    # comparten el valor.
    cuatri_db: dict[int, str | None] = {}
    for catedra_id, _codigo, _vac, _vigente, cuatrimestre, _congelada in filas_db:
        cuatri_db.setdefault(catedra_id, cuatrimestre)

    # Cátedras donde la fuente ya publica otro cuatrimestre: la misma clave
    # (catedra_id, codigo) apunta a una comisión distinta, así que escribir ahí
    # sería pisar la oferta vieja con cupos de la nueva. Se saltea completa.
    saltadas: set[int] = set()
    for catedra_id, pagina in paginas.items():
        esperado = cuatri_db.get(catedra_id)
        if esperado is not None and pagina.cuatrimestre != esperado:
            saltadas.add(catedra_id)
            m.saltadas_por_cuatrimestre += 1
            print(
                f"VACANTES-WARN: catedra={catedra_id} la fuente publica "
                f"{pagina.cuatrimestre} y la DB tiene {esperado}, se saltea"
            )

    leidas = set(paginas) - saltadas

    fuente: dict[tuple[int, str], int | None] = {
        (catedra_id, codigo): valor
        for catedra_id in leidas
        for codigo, valor in paginas[catedra_id].vacantes.items()
    }

    db: dict[tuple[int, str], int | None] = {}
    for catedra_id, codigo, vacantes, vigente, _cuatrimestre, congelada in filas_db:
        if catedra_id not in leidas:
            continue
        if not vigente:
            # Escribir sobre oferta no vigente es inocuo (el generador la filtra)
            # pero es superficie de escritura que no hace falta.
            m.descartadas_no_vigente += 1
            continue
        db[(catedra_id, codigo)] = vacantes
        if congelada:
            m.en_materia_congelada += 1

    m.claves_consideradas = len(fuente)
    m.claves_db = len(db)
    m.matched = len(set(fuente) & set(db))
    m.sin_match_fuente = len(set(fuente) - set(db))
    m.sin_ver_db = len(set(db) - set(fuente))

    payload: list[tuple[int, str, int]] = []
    for clave in set(fuente) & set(db):
        nuevo, viejo = fuente[clave], db[clave]
        if nuevo is None:
            if viejo is not None:
                # La fuente publica 0 cuando una comisión se llena, así que esto
                # debería quedar en 0. Si empieza a aparecer, la fuente cambió de
                # convención y hay que revisar la regla (hoy: no escribir).
                m.nuevos_null_en_db += 1
            continue
        if nuevo != viejo:
            m.cambios += 1
            payload.append((clave[0], clave[1], nuevo))

    return payload


def actualizar(
    paginas: dict[int, PaginaVacantes],
    m: MetricasVacantes,
    *,
    dry_run: bool,
    forzar: bool,
) -> None:
    """Abre la conexión, calcula el diff y escribe. Raisea para hacer rollback."""
    with get_conn() as conn:
        if dry_run:
            # Read-only a nivel server: psycopg emite BEGIN READ ONLY y Postgres
            # rechaza cualquier escritura. Es una garantía más fuerte que una
            # rama de código, y es lo que hace seguro correr esto contra prod.
            conn.read_only = True

        # Si el scraper diario tiene los locks, morir rápido en vez de dejar la
        # conexión pinneada (y el compute de Neon despierto) esperando.
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '15s'")

        filas_db = conn.execute(SELECT_ESTADO).fetchall()
        payload = calcular_payload(paginas, filas_db, m)
        decision = evaluar_actualizacion(m, forzar=forzar)

        _imprimir_db(m, decision, payload, dry_run)

        if not decision.escribir:
            # Excepción (no return) para que el context manager haga rollback.
            raise _Abortar(decision.motivo)

        if dry_run or not payload:
            return

        rowcount = conn.execute(
            UPDATE_VACANTES,
            {
                "catedras": [p[0] for p in payload],
                "codigos": [p[1] for p in payload],
                "vacantes": [p[2] for p in payload],
            },
        ).rowcount
        warning = verificar_rowcount(rowcount, len(payload))
        if warning:
            print(f"VACANTES-WARN: {warning}")
        print(f"  {rowcount} filas actualizadas")


class _Abortar(RuntimeError):
    """Corta la transacción sin escribir. La maneja `main`."""


def _imprimir_fetch(m: MetricasVacantes, segundos: float) -> None:
    print("─ Fetch ────────────────────────────────────────")
    print(f"  {m.paginas_totales} cátedras en el índice · {segundos:.0f}s")
    print(
        f"  paginas_ok {m.paginas_ok}  http_error {m.paginas_http_error}  "
        f"sin_parse {m.paginas_sin_parse}  shape_mala {m.paginas_shape_mala}  "
        f"catedra_mismatch {m.paginas_catedra_mismatch}"
    )
    print("─ Claves ───────────────────────────────────────")
    print(
        f"  claves_fuente {m.claves_fuente} "
        f"(duplicadas_en_pagina {m.duplicadas_en_pagina})"
    )
    print(
        f"  con_valor {m.con_valor}  sin_valor {m.sin_valor}  "
        f"fuera_de_rango {m.fuera_de_rango}"
    )
    if m.valores_vistos:
        ordenados = sorted(m.valores_vistos)
        mediana = ordenados[len(ordenados) // 2]
        print(
            f"  rango observado: min {ordenados[0]}  max {ordenados[-1]}  "
            f"mediana {mediana}"
        )


def _destino_db() -> str:
    """Host y base del DATABASE_URL, sin credenciales.

    Se loguea porque `backend/.env` trae un DATABASE_URL local: si te olvidás de
    pasar el de prod, la corrida apunta a la DB de desarrollo y el resultado
    parece bueno sin serlo.
    """
    from urllib.parse import urlparse

    from .config import DATABASE_URL

    partes = urlparse(DATABASE_URL or "")
    base = (partes.path or "").lstrip("/") or "?"
    return f"{partes.hostname or 'local'}/{base}"


def _imprimir_db(
    m: MetricasVacantes, decision, payload: list, dry_run: bool
) -> None:
    print(f"─ DB ({_destino_db()}) ─────────────────────────")
    print(
        f"  claves_db {m.claves_db}  "
        f"saltadas_por_cuatrimestre {m.saltadas_por_cuatrimestre} cátedras  "
        f"descartadas_no_vigente {m.descartadas_no_vigente}  "
        f"en_materia_congelada {m.en_materia_congelada}"
    )
    pct = f" ({m.matched / m.claves_db:.1%} de la DB)" if m.claves_db else ""
    print(f"  matched {m.matched}{pct}")
    print(f"  sin_match_fuente {m.sin_match_fuente}  sin_ver_db {m.sin_ver_db}")
    print("─ Diff ─────────────────────────────────────────")
    print(f"  cambios {m.cambios} de {m.matched} matched")
    print(f"  nuevos_null_en_db {m.nuevos_null_en_db}")

    if dry_run and payload:
        print(f"  muestra (hasta 40 de {len(payload)}):")
        for catedra_id, codigo, nuevo in payload[:40]:
            print(f"    catedra={catedra_id} com={codigo} → {nuevo}")

    print("─ Decisión ─────────────────────────────────────")
    verbo = "ESCRIBIRÍA" if dry_run else "ESCRIBE"
    estado = "sí" if decision.escribir else "NO"
    print(f"  {verbo}: {estado} — {decision.motivo}")
    print(f"  payload: {len(payload)} filas")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Actualiza sólo cursos.vacantes (job de alta frecuencia)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetchea y calcula el diff sin escribir nada. La transacción se abre "
            "READ ONLY, así que el server rechaza escrituras: es seguro contra "
            "producción."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Procesa solo las primeras N cátedras del índice",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DELAY_SECONDS,
        help=f"Segundos entre requests (default: {DELAY_SECONDS})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Destraba las guardas relativas (cobertura, cambios masivos). No "
            "destraba el índice vacío ni el SELECT sin resultados."
        ),
    )
    args = parser.parse_args(argv)

    m = MetricasVacantes()

    try:
        entries = discover_catedras()
    except Exception as exc:
        print(f"VACANTES-ABORT: no se pudo leer el índice: {exc!r}")
        print("No se tocó la DB.")
        return 1

    if args.limit is not None:
        entries = entries[: args.limit]
        print(f"--limit aplicado: {len(entries)} cátedras a procesar")

    inicio = time.monotonic()
    paginas = recolectar(
        entries, m, delay=args.delay, verbose=args.limit is not None
    )
    segundos_fetch = time.monotonic() - inicio
    _imprimir_fetch(m, segundos_fetch)

    # Con --limit el piso de cátedras no aplica: se pidió un subconjunto a mano.
    # El resto de las guardas sí, porque `claves_db` se acota a lo que se leyó.
    forzar_conteo = args.force or (
        args.limit is not None and len(entries) < MIN_CATEDRAS
    )
    decision = evaluar_fetch(m, forzar=forzar_conteo)
    if not decision.escribir:
        print(f"VACANTES-ABORT: {decision.motivo}")
        print("No se tocó la DB.")
        return 1

    inicio_db = time.monotonic()
    try:
        actualizar(paginas, m, dry_run=args.dry_run, forzar=args.force)
    except _Abortar as exc:
        print(f"VACANTES-ABORT: {exc}")
        print("Rollback: no se escribió nada.")
        return 1
    except Exception as exc:
        print(f"VACANTES-ABORT: error contra la DB: {exc!r}")
        print("Rollback: no se escribió nada.")
        return 1
    segundos_db = time.monotonic() - inicio_db

    modo = "dry-run (no escribió)" if args.dry_run else "escrito"
    print(
        f"VACANTES-OK: {modo} · {m.paginas_ok}/{m.paginas_totales} páginas · "
        f"matched {m.matched} · {m.cambios} cambios · "
        f"fetch {segundos_fetch:.0f}s db {segundos_db:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
