from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable

import psycopg

from .config import DATABASE_URL
from .parse import CatedraDetalle

INSERT_CURSO = """
    INSERT INTO cursos (
        catedra_id, tipo, codigo, dia, hora_inicio, hora_fin,
        profesor, vacantes, obligatorio, aula, sede, observaciones, parte_de_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada (revisar .env)")
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


def upsert_materia(
    conn: psycopg.Connection,
    codigo: int,
    nombre: str,
    carrera: str | None,
) -> None:
    # Carrera sólo se setea en INSERT y cuando el row existente la tiene NULL,
    # para no pisar el dato si la misma materia aparece scrapeada bajo otra
    # pestaña en una corrida posterior. La dedup por catedra_id en discover.py
    # asegura que el primer match gana, consistente con el modelo 1:N.
    conn.execute(
        """
        INSERT INTO materias (codigo, nombre, carrera)
        VALUES (%s, %s, %s)
        ON CONFLICT (codigo) DO UPDATE SET
            nombre  = EXCLUDED.nombre,
            carrera = COALESCE(materias.carrera, EXCLUDED.carrera)
        """,
        (codigo, nombre, carrera),
    )


def upsert_catedra(
    conn: psycopg.Connection,
    catedra_id: int,
    materia_codigo: int,
    numero: str | None,
    titular: str | None,
    cuatrimestre: str | None,
) -> None:
    # Verla en la fuente la marca vigente: una cátedra que se dejó de dictar y
    # vuelve el cuatrimestre siguiente se reactiva sola, sin intervención.
    conn.execute(
        """
        INSERT INTO catedras (
            id, materia_codigo, numero, titular, cuatrimestre, vigente, last_seen_at
        )
        VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
        ON CONFLICT (id) DO UPDATE SET
            materia_codigo = EXCLUDED.materia_codigo,
            numero         = EXCLUDED.numero,
            titular        = EXCLUDED.titular,
            cuatrimestre   = EXCLUDED.cuatrimestre,
            vigente        = TRUE,
            last_seen_at   = NOW()
        """,
        (catedra_id, materia_codigo, numero, titular, cuatrimestre),
    )


def es_materia_anual(conn: psycopg.Connection, materia_codigo: int) -> bool:
    row = conn.execute(
        "SELECT anual FROM materias WHERE codigo = %s", (materia_codigo,)
    ).fetchone()
    return bool(row and row[0])


def replace_cursos(conn: psycopg.Connection, detalle: CatedraDetalle) -> None:
    """Reemplaza los cursos de la cátedra: borra todo y re-inserta.

    Más simple y robusto que upsert por (catedra, tipo, codigo) cuando una
    comisión deja de existir entre cuatrimestres.
    """
    if not detalle.cursos and es_materia_anual(conn, detalle.materia_codigo):
        # Materia anual con detalle vacío: la fuente la publica un solo
        # cuatrimestre, así que vaciarla acá borraría los horarios que se están
        # cursando y no habría corrida que los repusiera.
        print(
            f"  catedra={detalle.catedra_id}: materia anual sin cursos en la fuente, "
            f"se conservan los guardados"
        )
        return

    conn.execute("DELETE FROM cursos WHERE catedra_id = %s", (detalle.catedra_id,))
    if not detalle.cursos:
        return

    def _row(c, parte_de_id=None):
        return (
            detalle.catedra_id,
            c.tipo,
            c.codigo,
            c.dia,
            c.hora_inicio,
            c.hora_fin,
            c.profesor,
            c.vacantes,
            c.obligatorio,
            c.aula,
            c.sede,
            c.observaciones,
            parte_de_id,
        )

    with conn.cursor() as cur:
        # Dos pasadas: las partes necesitan el id de su principal, así que la
        # primera vuelve con RETURNING (un result set por fila, en orden de entrada).
        cur.executemany(INSERT_CURSO, [_row(c) for c in detalle.cursos], returning=True)
        ids = []
        while True:
            ids.append(cur.fetchone()[0])
            if not cur.nextset():
                break

        partes = [
            _row(p, parte_de_id=cid)
            for cid, c in zip(ids, detalle.cursos)
            for p in c.partes
        ]
        if partes:
            cur.executemany(INSERT_CURSO, partes)


def resolve_obligatorio(conn: psycopg.Connection, catedra_id: int) -> None:
    """Resuelve `cursos.obligatorio` de las comisiones de la cátedra a filas en
    `comision_obliga`. Aplica matching difuso: 'l' (ele minúscula) → 'I',
    'Ï' → 'I', UPPER y TRIM. Esto resuelve typos comunes de la fuente
    ('Il', 'll', 'l', 'Ï') sin romper códigos legítimos.

    Idempotente: las filas previas se borran vía CASCADE cuando replace_cursos
    elimina los cursos.

    Sólo participan filas principales (`parte_de_id IS NULL`). Del lado de la
    comisión porque las partes repiten el `obligatorio` del padre y duplicarían el
    teórico dentro de la opción, dejando todo plan auto-solapado. Del lado del
    teórico porque una parte comparte el código de su principal y matchearía dos veces.
    """
    conn.execute(
        r"""
        INSERT INTO comision_obliga (comision_id, obliga_a_id)
        SELECT DISTINCT cu.id, t.id
          FROM cursos cu
          JOIN cursos t ON t.catedra_id = cu.catedra_id
                         AND t.id <> cu.id
                         AND t.tipo IN ('teorico', 'seminario')
                         AND t.parte_de_id IS NULL
                         AND UPPER(REPLACE(REPLACE(t.codigo, 'l', 'I'), 'Ï', 'I')) = ANY(
                               SELECT UPPER(REPLACE(REPLACE(TRIM(token), 'l', 'I'), 'Ï', 'I'))
                                 FROM regexp_split_to_table(cu.obligatorio, '\s*-\s*') AS token
                                WHERE TRIM(token) <> ''
                             )
         WHERE cu.catedra_id = %s
           AND cu.tipo = 'comision'
           AND cu.parte_de_id IS NULL
           AND cu.obligatorio IS NOT NULL
        ON CONFLICT DO NOTHING
        """,
        (catedra_id,),
    )


def contar_vigentes(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM catedras WHERE vigente").fetchone()
    return row[0] if row else 0


def sync_materias_anuales(conn: psycopg.Connection, codigos: Iterable[int]) -> int:
    """Sincroniza `materias.anual` con la lista del código. Devuelve filas tocadas.

    La constante `MATERIAS_ANUALES` es la fuente de verdad: sacar un código de ahí
    lo desmarca en la corrida siguiente. El `WHERE` evita reescribir toda la tabla
    en cada corrida.
    """
    ids = list(codigos)
    return conn.execute(
        """
        UPDATE materias SET anual = (codigo = ANY(%(ids)s))
         WHERE anual <> (codigo = ANY(%(ids)s))
        """,
        {"ids": ids},
    ).rowcount


# Materias anuales que no figuran en el índice de esta corrida. Se cursan todo el
# año pero la fuente sólo las publica en el 1er cuatrimestre, así que su ausencia
# no significa que se dejaron de dictar. Si la materia SÍ aparece, sus cátedras se
# barren normal: ahí la ausencia de una cátedra puntual sí es información.
_ANUALES_AUSENTES_CTE = """
    WITH anuales_ausentes AS (
        SELECT m.codigo
          FROM materias m
         WHERE m.anual
           AND NOT EXISTS (
               SELECT 1 FROM catedras c
                WHERE c.materia_codigo = m.codigo AND c.id = ANY(%(vistas)s)
           )
    )
"""


def listar_a_dar_de_baja(
    conn: psycopg.Connection, vistas: Iterable[int]
) -> list[tuple[int, str | None]]:
    """Cátedras vigentes que no aparecieron en el índice de esta corrida.

    Sólo para el reporte del --dry-run-sweep; el sweep real no la necesita.
    """
    ids = list(vistas)
    if not ids:
        return []
    rows = conn.execute(
        _ANUALES_AUSENTES_CTE
        + """
        SELECT ca.id, m.nombre
          FROM catedras ca
          JOIN materias m ON m.codigo = ca.materia_codigo
         WHERE ca.vigente AND ca.id <> ALL(%(vistas)s)
           AND ca.materia_codigo NOT IN (SELECT codigo FROM anuales_ausentes)
         ORDER BY ca.id
        """,
        {"vistas": ids},
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def listar_exentas_por_anual(
    conn: psycopg.Connection, vistas: Iterable[int]
) -> list[tuple[int, str | None]]:
    """Cátedras vigentes que se salvan del sweep por pertenecer a una materia anual."""
    ids = list(vistas)
    if not ids:
        return []
    rows = conn.execute(
        _ANUALES_AUSENTES_CTE
        + """
        SELECT ca.id, m.nombre
          FROM catedras ca
          JOIN materias m ON m.codigo = ca.materia_codigo
         WHERE ca.vigente AND ca.id <> ALL(%(vistas)s)
           AND ca.materia_codigo IN (SELECT codigo FROM anuales_ausentes)
         ORDER BY ca.id
        """,
        {"vistas": ids},
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def marcar_oferta_congelada(conn: psycopg.Connection, vistas: Iterable[int]) -> int:
    """Marca las materias cuyos datos publicados son de un cuatrimestre anterior.

    Es el mismo hecho que exime a una anual del sweep: la fuente dejó de
    publicarla. Lo consume `solo_con_cupos`, que no puede aplicar sobre cupos
    viejos — el alumno de una anual ya está cursando aunque figure sin vacantes.

    Va detrás de las guardas de `evaluar_sweep`: con un índice a medio cargar no
    se puede concluir que una materia dejó de publicarse.
    """
    ids = list(vistas)
    if not ids:
        raise ValueError("marcar_oferta_congelada: lista de vistas vacía, se aborta")
    # El `WHERE` evita reescribir la tabla entera y, de paso, apaga el flag de una
    # materia que dejó de estar en MATERIAS_ANUALES (nunca entra en el CTE).
    return conn.execute(
        _ANUALES_AUSENTES_CTE
        + """
        UPDATE materias m
           SET oferta_congelada = (m.codigo IN (SELECT codigo FROM anuales_ausentes))
         WHERE m.oferta_congelada
               <> (m.codigo IN (SELECT codigo FROM anuales_ausentes))
        """,
        {"vistas": ids},
    ).rowcount


def dar_de_baja_no_vistas(conn: psycopg.Connection, vistas: Iterable[int]) -> int:
    """Marca `vigente = FALSE` las cátedras que no figuran en el índice actual.

    No borra nada: los cursos quedan en la DB para que las reseñas de esa cátedra
    (incluida la validación del profesor) sigan funcionando. Revertible con un
    `UPDATE catedras SET vigente = TRUE`.
    """
    ids = list(vistas)
    # `id <> ALL(ARRAY[]::int[])` es TRUE para toda fila: con una lista vacía esto
    # daría de baja la oferta entera. `evaluar_sweep` ya lo impide; esto es el
    # cinturón sobre los tirantes, porque el error sería silencioso y total.
    if not ids:
        raise ValueError("dar_de_baja_no_vistas: lista de vistas vacía, se aborta")
    return conn.execute(
        _ANUALES_AUSENTES_CTE
        + """
        UPDATE catedras SET vigente = FALSE
         WHERE vigente AND id <> ALL(%(vistas)s)
           AND materia_codigo NOT IN (SELECT codigo FROM anuales_ausentes)
        """,
        {"vistas": ids},
    ).rowcount


def save_detalle(
    conn: psycopg.Connection,
    detalle: CatedraDetalle,
    carrera: str | None = None,
) -> None:
    upsert_materia(conn, detalle.materia_codigo, detalle.materia_nombre, carrera)
    upsert_catedra(
        conn,
        detalle.catedra_id,
        detalle.materia_codigo,
        detalle.numero,
        detalle.titular,
        detalle.cuatrimestre,
    )
    replace_cursos(conn, detalle)
    resolve_obligatorio(conn, detalle.catedra_id)
