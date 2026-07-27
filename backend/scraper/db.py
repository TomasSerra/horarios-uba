from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable

import psycopg

from .config import DATABASE_URL
from .parse import CatedraDetalle


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


def replace_cursos(conn: psycopg.Connection, detalle: CatedraDetalle) -> None:
    """Reemplaza los cursos de la cátedra: borra todo y re-inserta.

    Más simple y robusto que upsert por (catedra, tipo, codigo) cuando una
    comisión deja de existir entre cuatrimestres.
    """
    conn.execute("DELETE FROM cursos WHERE catedra_id = %s", (detalle.catedra_id,))
    if not detalle.cursos:
        return
    rows = [
        (
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
        )
        for c in detalle.cursos
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO cursos (
                catedra_id, tipo, codigo, dia, hora_inicio, hora_fin,
                profesor, vacantes, obligatorio, aula, sede, observaciones
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )


def resolve_obligatorio(conn: psycopg.Connection, catedra_id: int) -> None:
    """Resuelve `cursos.obligatorio` de las comisiones de la cátedra a filas en
    `comision_obliga`. Aplica matching difuso: 'l' (ele minúscula) → 'I',
    'Ï' → 'I', UPPER y TRIM. Esto resuelve typos comunes de la fuente
    ('Il', 'll', 'l', 'Ï') sin romper códigos legítimos.

    Idempotente: las filas previas se borran vía CASCADE cuando replace_cursos
    elimina los cursos.
    """
    conn.execute(
        r"""
        INSERT INTO comision_obliga (comision_id, obliga_a_id)
        SELECT DISTINCT cu.id, t.id
          FROM cursos cu
          JOIN cursos t ON t.catedra_id = cu.catedra_id
                         AND t.id <> cu.id
                         AND t.tipo IN ('teorico', 'seminario')
                         AND UPPER(REPLACE(REPLACE(t.codigo, 'l', 'I'), 'Ï', 'I')) = ANY(
                               SELECT UPPER(REPLACE(REPLACE(TRIM(token), 'l', 'I'), 'Ï', 'I'))
                                 FROM regexp_split_to_table(cu.obligatorio, '\s*-\s*') AS token
                                WHERE TRIM(token) <> ''
                             )
         WHERE cu.catedra_id = %s
           AND cu.tipo = 'comision'
           AND cu.obligatorio IS NOT NULL
        ON CONFLICT DO NOTHING
        """,
        (catedra_id,),
    )


def contar_vigentes(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM catedras WHERE vigente").fetchone()
    return row[0] if row else 0


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
        """
        SELECT ca.id, m.nombre
          FROM catedras ca
          JOIN materias m ON m.codigo = ca.materia_codigo
         WHERE ca.vigente AND ca.id <> ALL(%s)
         ORDER BY ca.id
        """,
        (ids,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


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
        "UPDATE catedras SET vigente = FALSE WHERE vigente AND id <> ALL(%s)",
        (ids,),
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
