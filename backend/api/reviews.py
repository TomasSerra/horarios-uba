from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from .auth import AuthUser, current_user, optional_user
from .db import pool
from .subs import has_active_subscription

router = APIRouter()

# Página de reseñas (detalle) y ranking (listado). El listado muestra menos por
# página porque cada card es chica.
PAGE_SIZE = 10
RANK_PAGE_SIZE = 16
# Free (anónimo o sin Pro) solo ve las primeras N reseñas de una cátedra; el
# resto queda detrás del paywall.
FREE_REVIEW_LIMIT = 5

# Plegado de tildes para el buscador del ranking: mapea cada vocal acentuada (y
# la ñ) a su base. Evita depender de la extensión `unaccent` de Postgres. El
# lado SQL usa translate() con estas mismas tablas; el patrón se pliega acá con
# _fold(), replicando el normalizar() del front (NFD + strip de marcas + lower).
_FOLD_FROM = "áéíóúüñàèìòùäëïöâêîôûãõ"
_FOLD_TO = "aeiouunaeiouaeioaeiouao"


def _fold(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


# --- Modelos ------------------------------------------------------------------


class CatedraRankItem(BaseModel):
    catedra_id: int
    materia_codigo: int
    materia_nombre: str
    numero: str | None = None
    titular: str | None = None
    cuatrimestre: str | None = None
    avg_rating: float | None = None
    review_count: int


class CatedraRankPage(BaseModel):
    items: list[CatedraRankItem]
    total: int
    page: int
    page_size: int


class ReviewItem(BaseModel):
    id: int
    # Nota de la cátedra.
    rating: int
    comment: str | None = None
    # Profesor puntuado y su nota, opcionales (o los dos o ninguno).
    profesor: str | None = None
    profesor_rating: int | None = None
    anio: int
    created_at: datetime
    updated_at: datetime


class ProfesorStats(BaseModel):
    profesor: str
    avg_rating: float | None = None
    review_count: int


class CatedraHeader(BaseModel):
    id: int
    materia_codigo: int
    materia_nombre: str
    numero: str | None = None
    titular: str | None = None
    cuatrimestre: str | None = None


class CatedraReviewsPage(BaseModel):
    catedra: CatedraHeader
    avg_rating: float | None = None
    review_count: int
    # {1..5: cantidad}. En JSON las claves viajan como string.
    distribution: dict[int, int]
    # Todos los profesores de la cátedra (comisiones) con sus agregados de reseñas.
    # No se filtra por el `profesor` seleccionado: sirve para ver el promedio de
    # cada uno de un vistazo antes de filtrar.
    profesores: list[ProfesorStats]
    my_review: ReviewItem | None = None
    # Reseñas de OTROS usuarios (la propia se muestra aparte en `my_review`).
    reviews: list[ReviewItem]
    total: int
    page: int
    page_size: int
    # True cuando la lista se recortó por el gate free (hay más reseñas que las
    # que se devolvieron y el usuario no es Pro).
    locked: bool = False


class ReviewUpsert(BaseModel):
    # Nota de la cátedra (obligatoria).
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    # Profesor y su nota: opcionales, pero emparejados (o los dos o ninguno).
    profesor: str | None = Field(default=None, min_length=1)
    profesor_rating: int | None = Field(default=None, ge=1, le=5)
    # Cota superior dinámica: no tiene sentido reseñar una cursada futura.
    anio: int = Field(ge=2000, le=datetime.now().year)

    @model_validator(mode="after")
    def _profesor_emparejado(self) -> "ReviewUpsert":
        if (self.profesor is None) != (self.profesor_rating is None):
            raise ValueError(
                "profesor y profesor_rating deben venir juntos o ninguno"
            )
        return self


SortKey = Literal["mejores", "peores", "mas_resenas", "materia"]

# ORDER BY por cada `sort`. Constantes fijas (no viene input del usuario acá): el
# valor ya está validado por el Literal, así que no hay riesgo de inyección.
_ORDER_BY: dict[str, str] = {
    "mejores": "AVG(r.rating) DESC NULLS LAST, COUNT(r.id) DESC, m.nombre ASC, ca.id ASC",
    "peores": "AVG(r.rating) ASC NULLS LAST, COUNT(r.id) DESC, m.nombre ASC, ca.id ASC",
    "mas_resenas": "COUNT(r.id) DESC, AVG(r.rating) DESC NULLS LAST, m.nombre ASC, ca.id ASC",
    "materia": "m.nombre ASC, ca.numero ASC, ca.id ASC",
}


# --- Ranking (público) --------------------------------------------------------


@router.get("", response_model=CatedraRankPage)
def list_catedras(
    carrera: str = Query(..., description="Slug de carrera"),
    q: str | None = Query(None, description="Busca en materia, titular o número"),
    sort: SortKey = Query("mejores"),
    page: int = Query(1, ge=1),
) -> CatedraRankPage:
    offset = (page - 1) * RANK_PAGE_SIZE
    # Buscador insensible a tildes y mayúsculas: plegamos el patrón acá y las
    # columnas con translate() en SQL (mismo criterio que el front).
    pattern = f"%{_fold(q)}%" if q else None
    # `COUNT(*) OVER()` devuelve el total de grupos (cátedras que matchean) en la
    # misma query: paginamos sin una segunda consulta de total.
    sql = f"""
        SELECT ca.id AS catedra_id,
               m.codigo AS materia_codigo,
               m.nombre AS materia_nombre,
               ca.numero, ca.titular, ca.cuatrimestre,
               AVG(r.rating)::float AS avg_rating,
               COUNT(r.id) AS review_count,
               COUNT(*) OVER() AS total_count
          FROM catedras ca
          JOIN materias m ON m.codigo = ca.materia_codigo
          LEFT JOIN catedra_reviews r ON r.catedra_id = ca.id
         WHERE m.carrera = %(carrera)s
           AND (%(pattern)s::text IS NULL
                OR translate(lower(m.nombre), %(fold_from)s, %(fold_to)s) LIKE %(pattern)s
                OR translate(lower(ca.titular), %(fold_from)s, %(fold_to)s) LIKE %(pattern)s
                OR translate(lower(ca.numero), %(fold_from)s, %(fold_to)s) LIKE %(pattern)s)
         GROUP BY ca.id, ca.numero, ca.titular, ca.cuatrimestre, m.codigo, m.nombre
         ORDER BY {_ORDER_BY[sort]}
         LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {
        "carrera": carrera,
        "pattern": pattern,
        "fold_from": _FOLD_FROM,
        "fold_to": _FOLD_TO,
        "limit": RANK_PAGE_SIZE,
        "offset": offset,
    }
    with pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    total = rows[0]["total_count"] if rows else 0
    items = [
        CatedraRankItem(
            catedra_id=r["catedra_id"],
            materia_codigo=r["materia_codigo"],
            materia_nombre=r["materia_nombre"],
            numero=r["numero"],
            titular=r["titular"],
            cuatrimestre=r["cuatrimestre"],
            avg_rating=(
                round(r["avg_rating"], 2) if r["avg_rating"] is not None else None
            ),
            review_count=r["review_count"],
        )
        for r in rows
    ]
    return CatedraRankPage(
        items=items, total=total, page=page, page_size=RANK_PAGE_SIZE
    )


# --- Detalle: cabecera + agregados + mi reseña + página de reseñas ------------


@router.get("/{catedra_id}/reviews", response_model=CatedraReviewsPage)
def get_catedra_reviews(
    catedra_id: int,
    page: int = Query(1, ge=1),
    rating: int | None = Query(None, ge=1, le=5),
    profesor: str | None = Query(None, description="Filtra el listado por profesor"),
    user: AuthUser | None = Depends(optional_user),
) -> CatedraReviewsPage:
    uid = user.id if user else None
    with pool.connection() as conn:
        is_pro = uid is not None and has_active_subscription(conn, uid)
        # Free (anónimo o sin Pro) no pagina: siempre las primeras N.
        limit = PAGE_SIZE if is_pro else FREE_REVIEW_LIMIT
        offset = (page - 1) * PAGE_SIZE if is_pro else 0
        cat = conn.execute(
            """
            SELECT ca.id, ca.materia_codigo, m.nombre AS materia_nombre,
                   ca.numero, ca.titular, ca.cuatrimestre
              FROM catedras ca
              JOIN materias m ON m.codigo = ca.materia_codigo
             WHERE ca.id = %s
            """,
            (catedra_id,),
        ).fetchone()
        if cat is None:
            raise HTTPException(status_code=404, detail="Cátedra no encontrada")

        dist_rows = conn.execute(
            "SELECT rating, COUNT(*) AS cnt FROM catedra_reviews "
            "WHERE catedra_id = %s GROUP BY rating",
            (catedra_id,),
        ).fetchall()

        my_row = None
        if uid is not None:
            my_row = conn.execute(
                "SELECT id, rating, comment, profesor, profesor_rating, anio, "
                "created_at, updated_at "
                "FROM catedra_reviews WHERE catedra_id = %s AND clerk_user_id = %s",
                (catedra_id, uid),
            ).fetchone()

        # Todos los profesores de la cátedra (comisiones) + sus agregados de
        # reseñas. Se unen en Python: la lista base viene de cursos (incluye
        # profes sin reseñas) y los agregados de catedra_reviews.
        prof_rows = conn.execute(
            "SELECT DISTINCT profesor FROM cursos "
            "WHERE catedra_id = %s AND tipo = 'comision' AND profesor IS NOT NULL",
            (catedra_id,),
        ).fetchall()
        # El promedio del profesor sale de su nota dedicada (profesor_rating),
        # no del rating de la cátedra. Solo reseñas que puntuaron a un profesor.
        prof_stats_rows = conn.execute(
            "SELECT profesor, AVG(profesor_rating)::float AS avg_rating, "
            "COUNT(*) AS review_count "
            "FROM catedra_reviews "
            "WHERE catedra_id = %s AND profesor IS NOT NULL "
            "AND profesor_rating IS NOT NULL GROUP BY profesor",
            (catedra_id,),
        ).fetchall()

        # La propia se excluye del listado (se muestra aparte). `COUNT(*) OVER()`
        # da el total de reseñas de otros para paginar en una sola query.
        review_rows = conn.execute(
            """
            SELECT id, rating, comment, profesor, profesor_rating, anio,
                   created_at, updated_at,
                   COUNT(*) OVER() AS total_count
              FROM catedra_reviews
             WHERE catedra_id = %(catedra_id)s
               AND (%(uid)s::text IS NULL OR clerk_user_id <> %(uid)s)
               AND (%(rating)s::int IS NULL OR rating = %(rating)s)
               AND (%(profesor)s::text IS NULL OR profesor = %(profesor)s)
             ORDER BY anio DESC, created_at DESC
             LIMIT %(limit)s OFFSET %(offset)s
            """,
            {
                "catedra_id": catedra_id,
                "uid": uid,
                "rating": rating,
                "profesor": profesor,
                "limit": limit,
                "offset": offset,
            },
        ).fetchall()

    distribution = {i: 0 for i in range(1, 6)}
    total_reviews = 0
    weighted = 0
    for d in dist_rows:
        distribution[d["rating"]] = d["cnt"]
        total_reviews += d["cnt"]
        weighted += d["rating"] * d["cnt"]
    avg_rating = round(weighted / total_reviews, 2) if total_reviews else None

    total_others = review_rows[0]["total_count"] if review_rows else 0
    locked = (not is_pro) and total_others > FREE_REVIEW_LIMIT

    # Merge profes de la cátedra + agregados. Union: incluye profes sin reseñas y
    # también los que tengan reseñas pero ya no figuren en cursos (por robustez).
    stats_by_prof = {s["profesor"]: s for s in prof_stats_rows}
    nombres = {r["profesor"] for r in prof_rows} | set(stats_by_prof)
    profesores = []
    for nombre in sorted(nombres):
        s = stats_by_prof.get(nombre)
        profesores.append(
            ProfesorStats(
                profesor=nombre,
                avg_rating=(
                    round(s["avg_rating"], 2)
                    if s and s["avg_rating"] is not None
                    else None
                ),
                review_count=s["review_count"] if s else 0,
            )
        )

    return CatedraReviewsPage(
        catedra=CatedraHeader(
            id=cat["id"],
            materia_codigo=cat["materia_codigo"],
            materia_nombre=cat["materia_nombre"],
            numero=cat["numero"],
            titular=cat["titular"],
            cuatrimestre=cat["cuatrimestre"],
        ),
        avg_rating=avg_rating,
        review_count=total_reviews,
        distribution=distribution,
        profesores=profesores,
        my_review=ReviewItem(**my_row) if my_row else None,
        reviews=[
            ReviewItem(
                id=r["id"],
                rating=r["rating"],
                comment=r["comment"],
                profesor=r["profesor"],
                profesor_rating=r["profesor_rating"],
                anio=r["anio"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in review_rows
        ],
        total=total_others,
        page=page,
        page_size=PAGE_SIZE,
        locked=locked,
    )


# --- Escritura (requiere login; NO requiere Pro) ------------------------------


@router.put("/{catedra_id}/reviews", response_model=ReviewItem)
def upsert_review(
    catedra_id: int,
    body: ReviewUpsert,
    user: AuthUser = Depends(current_user),
) -> ReviewItem:
    comment = body.comment.strip() if body.comment else None
    if not comment:
        comment = None
    with pool.connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM catedras WHERE id = %s", (catedra_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Cátedra no encontrada")
        # Si puntuó a un profesor, tiene que ser uno de los que dictan comisiones de
        # la cátedra (el front lo elige de una lista, esto blinda contra requests
        # armadas a mano). Sin profesor no hace falta validar.
        if body.profesor is not None:
            prof_ok = conn.execute(
                "SELECT 1 FROM cursos "
                "WHERE catedra_id = %s AND tipo = 'comision' AND profesor = %s",
                (catedra_id, body.profesor),
            ).fetchone()
            if prof_ok is None:
                raise HTTPException(
                    status_code=400, detail="El profesor no pertenece a esta cátedra"
                )
        row = conn.execute(
            """
            INSERT INTO catedra_reviews
                (catedra_id, clerk_user_id, rating, comment,
                 profesor, profesor_rating, anio)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (catedra_id, clerk_user_id) DO UPDATE SET
                rating          = EXCLUDED.rating,
                comment         = EXCLUDED.comment,
                profesor        = EXCLUDED.profesor,
                profesor_rating = EXCLUDED.profesor_rating,
                anio            = EXCLUDED.anio,
                updated_at      = NOW()
            RETURNING id, rating, comment, profesor, profesor_rating, anio,
                      created_at, updated_at
            """,
            (
                catedra_id,
                user.id,
                body.rating,
                comment,
                body.profesor,
                body.profesor_rating,
                body.anio,
            ),
        ).fetchone()
        conn.commit()
    return ReviewItem(**row)


@router.delete("/{catedra_id}/reviews")
def delete_review(
    catedra_id: int,
    user: AuthUser = Depends(current_user),
) -> dict:
    with pool.connection() as conn:
        deleted = conn.execute(
            "DELETE FROM catedra_reviews WHERE catedra_id = %s AND clerk_user_id = %s",
            (catedra_id, user.id),
        ).rowcount
        conn.commit()
    if not deleted:
        raise HTTPException(
            status_code=404, detail="No tenés una reseña en esta cátedra"
        )
    return {"ok": True}
