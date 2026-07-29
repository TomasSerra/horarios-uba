from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from .auth import AuthUser, current_user
from .db import pool
from .planes import Plan, FranjaExcluida
from .subs import has_active_subscription

router = APIRouter()


class FavoriteFilters(BaseModel):
    dias_excluidos: list[str] = []
    franjas_excluidas: list[FranjaExcluida] = []
    sedes_permitidas: list[str] = []
    max_bache_horas: float | None = None
    min_dias_semana: int | None = None
    max_dias_semana: int | None = None
    min_horas_dia: float | None = None
    max_horas_dia: float | None = None
    solo_con_cupos: bool = False
    # Por materia: lo que el usuario tenía elegido (cátedra fija + profesores + sede).
    materias: list[dict] = []


NOMBRE_MAX = 80
DESCRIPCION_MAX = 300


class FavoriteMeta(BaseModel):
    nombre: str = Field(max_length=NOMBRE_MAX)
    descripcion: str | None = Field(default=None, max_length=DESCRIPCION_MAX)

    @field_validator("nombre")
    @classmethod
    def _clean_nombre(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre no puede estar vacío")
        return v

    @field_validator("descripcion")
    @classmethod
    def _clean_descripcion(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


class FavoriteCreate(FavoriteMeta):
    plan: Plan
    filters: FavoriteFilters | None = None


# Se manda completo, no campo por campo: es un form de dos campos, y así borrar
# la descripción es explícito (mandar null) en vez de ambiguo.
class FavoriteUpdate(FavoriteMeta):
    pass


class FavoriteCreateResponse(BaseModel):
    id: int
    created_at: datetime


class Favorite(BaseModel):
    id: int
    plan: Plan
    filters: FavoriteFilters | None = None
    # Nullables: los favoritos guardados antes del modal de nombre no tienen
    # ninguno de los dos. El FE los muestra como "Sin nombre".
    nombre: str | None = None
    descripcion: str | None = None
    created_at: datetime


class FavoriteList(BaseModel):
    favorites: list[Favorite]


# Ver, editar y borrar los propios favoritos no requiere Pro (un user que dejó
# de ser Pro debería poder seguir viendo, ordenando y limpiando lo que guardó).
# Solo crear nuevos (POST) sigue siendo Pro.


@router.get("", response_model=FavoriteList)
def list_favorites(user: AuthUser = Depends(current_user)) -> FavoriteList:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, plan_data, filters_data, nombre, descripcion, created_at "
            "FROM favorite_plans "
            "WHERE clerk_user_id = %s ORDER BY created_at DESC",
            (user.id,),
        ).fetchall()
    return FavoriteList(
        favorites=[
            Favorite(
                id=r["id"],
                plan=Plan(**r["plan_data"]),
                filters=(
                    FavoriteFilters(**r["filters_data"]) if r["filters_data"] else None
                ),
                nombre=r["nombre"],
                descripcion=r["descripcion"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
    )


@router.post("", response_model=FavoriteCreateResponse)
def create_favorite(
    body: FavoriteCreate,
    user: AuthUser = Depends(current_user),
) -> FavoriteCreateResponse:
    with pool.connection() as conn:
        if not has_active_subscription(conn, user.id):
            raise HTTPException(
                status_code=403,
                detail="Guardar planes en favoritos es una función Pro.",
            )
        row = conn.execute(
            "INSERT INTO favorite_plans "
            "(clerk_user_id, plan_data, filters_data, nombre, descripcion) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at",
            (
                user.id,
                Jsonb(body.plan.model_dump(mode="json")),
                Jsonb(body.filters.model_dump(mode="json")) if body.filters else None,
                body.nombre,
                body.descripcion,
            ),
        ).fetchone()
        conn.commit()
    return FavoriteCreateResponse(id=row["id"], created_at=row["created_at"])


@router.patch("/{favorite_id}", response_model=FavoriteMeta)
def update_favorite(
    favorite_id: int,
    body: FavoriteUpdate,
    user: AuthUser = Depends(current_user),
) -> FavoriteMeta:
    with pool.connection() as conn:
        row = conn.execute(
            "UPDATE favorite_plans SET nombre = %s, descripcion = %s "
            "WHERE id = %s AND clerk_user_id = %s "
            "RETURNING nombre, descripcion",
            (body.nombre, body.descripcion, favorite_id, user.id),
        ).fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="Favorito no encontrado")
    return FavoriteMeta(nombre=row["nombre"], descripcion=row["descripcion"])


@router.delete("/{favorite_id}")
def delete_favorite(
    favorite_id: int,
    user: AuthUser = Depends(current_user),
) -> dict:
    with pool.connection() as conn:
        deleted = conn.execute(
            "DELETE FROM favorite_plans WHERE id = %s AND clerk_user_id = %s",
            (favorite_id, user.id),
        ).rowcount
        conn.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Favorito no encontrado")
    return {"ok": True}
