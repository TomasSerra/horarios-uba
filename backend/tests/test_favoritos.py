"""Tests de favoritos: gating Pro en create, list/update/delete sin gating Pro,
aislamiento entre usuarios, nombre/descripcion (incluido el caso de los
favoritos viejos que no tienen ninguno de los dos)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.auth import AuthUser
from api.favoritos import (
    DESCRIPCION_MAX,
    NOMBRE_MAX,
    FavoriteCreate,
    FavoriteFilters,
    FavoriteUpdate,
    create_favorite,
    delete_favorite,
    list_favorites,
    update_favorite,
)
from api.planes import CursoEnPlan, OpcionMateria, Plan


def _plan_minimo() -> Plan:
    return Plan(
        opciones=[
            OpcionMateria(
                materia_codigo=1,
                materia_nombre="M1",
                catedra_id=10,
                cursos=[
                    CursoEnPlan(id=100, tipo="comision", codigo="01", catedra_id=10),
                ],
            )
        ]
    )


def _row(**overrides) -> dict:
    """Fila de favorite_plans como la devuelve el SELECT."""
    row = {
        "id": 1,
        "plan_data": _plan_minimo().model_dump(mode="json"),
        "filters_data": None,
        "nombre": "Mi plan",
        "descripcion": None,
        "created_at": datetime.now(timezone.utc),
    }
    row.update(overrides)
    return row


# ----------------------------- create_favorite (Pro gating) -------------------

class TestCreateFavorite:
    def test_sin_sub_da_403(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        monkeypatch.setattr("api.favoritos.has_active_subscription", lambda conn, uid: False)
        body = FavoriteCreate(plan=_plan_minimo(), nombre="Mi plan")
        with pytest.raises(HTTPException) as exc:
            create_favorite(body, user=AuthUser(id="uid"))
        assert exc.value.status_code == 403
        assert "Pro" in exc.value.detail

    def test_con_sub_inserta(self, monkeypatch, fake_pool, fake_conn):
        now = datetime.now(timezone.utc)
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        monkeypatch.setattr("api.favoritos.has_active_subscription", lambda conn, uid: True)
        fake_conn.on("INSERT INTO favorite_plans", rows=[{"id": 42, "created_at": now}])
        body = FavoriteCreate(plan=_plan_minimo(), nombre="Mi plan")
        resp = create_favorite(body, user=AuthUser(id="uid"))
        assert resp.id == 42
        assert resp.created_at == now
        assert fake_conn.commits == 1

    def test_con_filters_none(self, monkeypatch, fake_pool, fake_conn):
        # filters=None: el segundo Jsonb param debe ser None.
        captured = {}

        def capture(sql, params):
            if "INSERT INTO favorite_plans" in sql:
                captured["params"] = params

        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        monkeypatch.setattr("api.favoritos.has_active_subscription", lambda conn, uid: True)
        fake_conn.on("INSERT INTO favorite_plans",
                     rows=[{"id": 1, "created_at": datetime.now(timezone.utc)}],
                     side_effect=capture)
        body = FavoriteCreate(plan=_plan_minimo(), filters=None, nombre="Mi plan")
        create_favorite(body, user=AuthUser(id="uid"))
        # Orden: (clerk_user_id, plan_data, filters_data, nombre, descripcion)
        assert captured["params"][2] is None

    def test_con_filters_serializa_jsonb(self, monkeypatch, fake_pool, fake_conn):
        captured = {}

        def capture(sql, params):
            if "INSERT INTO favorite_plans" in sql:
                captured["params"] = params

        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        monkeypatch.setattr("api.favoritos.has_active_subscription", lambda conn, uid: True)
        fake_conn.on("INSERT INTO favorite_plans",
                     rows=[{"id": 1, "created_at": datetime.now(timezone.utc)}],
                     side_effect=capture)
        body = FavoriteCreate(
            plan=_plan_minimo(),
            filters=FavoriteFilters(sedes_permitidas=["HY"]),
            nombre="Mi plan",
        )
        create_favorite(body, user=AuthUser(id="uid"))
        # filters_data no es None.
        assert captured["params"][2] is not None

    def test_persiste_nombre_y_descripcion(self, monkeypatch, fake_pool, fake_conn):
        captured = {}

        def capture(sql, params):
            if "INSERT INTO favorite_plans" in sql:
                captured["params"] = params

        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        monkeypatch.setattr("api.favoritos.has_active_subscription", lambda conn, uid: True)
        fake_conn.on("INSERT INTO favorite_plans",
                     rows=[{"id": 1, "created_at": datetime.now(timezone.utc)}],
                     side_effect=capture)
        body = FavoriteCreate(
            plan=_plan_minimo(), nombre="Cursada 2do cuatri", descripcion="El que me cierra"
        )
        create_favorite(body, user=AuthUser(id="uid"))
        assert captured["params"][3] == "Cursada 2do cuatri"
        assert captured["params"][4] == "El que me cierra"

    def test_sin_descripcion_persiste_none(self, monkeypatch, fake_pool, fake_conn):
        captured = {}

        def capture(sql, params):
            if "INSERT INTO favorite_plans" in sql:
                captured["params"] = params

        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        monkeypatch.setattr("api.favoritos.has_active_subscription", lambda conn, uid: True)
        fake_conn.on("INSERT INTO favorite_plans",
                     rows=[{"id": 1, "created_at": datetime.now(timezone.utc)}],
                     side_effect=capture)
        create_favorite(
            FavoriteCreate(plan=_plan_minimo(), nombre="Mi plan"), user=AuthUser(id="uid")
        )
        assert captured["params"][4] is None


# ----------------------------- validación de nombre/descripcion ---------------

# Los dos modelos heredan de FavoriteMeta, así que las reglas valen para ambos.
# FavoriteCreate necesita `plan`, FavoriteUpdate no: cada builder lo resuelve.
def _create(**kwargs) -> FavoriteCreate:
    return FavoriteCreate(plan=_plan_minimo(), **kwargs)


@pytest.mark.parametrize("build", [_create, FavoriteUpdate])
class TestValidacionMeta:
    def test_nombre_obligatorio(self, build):
        with pytest.raises(ValidationError):
            build()

    def test_nombre_vacio_rechazado(self, build):
        with pytest.raises(ValidationError):
            build(nombre="")

    def test_nombre_solo_whitespace_rechazado(self, build):
        with pytest.raises(ValidationError):
            build(nombre="   ")

    def test_nombre_se_trimea(self, build):
        assert build(nombre="  Mi plan  ").nombre == "Mi plan"

    def test_nombre_al_limite_pasa(self, build):
        assert len(build(nombre="a" * NOMBRE_MAX).nombre) == NOMBRE_MAX

    def test_nombre_excedido_rechazado(self, build):
        with pytest.raises(ValidationError):
            build(nombre="a" * (NOMBRE_MAX + 1))

    def test_descripcion_vacia_normaliza_a_none(self, build):
        assert build(nombre="Mi plan", descripcion="   ").descripcion is None

    def test_descripcion_se_trimea(self, build):
        assert build(nombre="Mi plan", descripcion="  hola  ").descripcion == "hola"

    def test_descripcion_al_limite_pasa(self, build):
        d = build(nombre="Mi plan", descripcion="a" * DESCRIPCION_MAX).descripcion
        assert len(d) == DESCRIPCION_MAX

    def test_descripcion_excedida_rechazada(self, build):
        with pytest.raises(ValidationError):
            build(nombre="Mi plan", descripcion="a" * (DESCRIPCION_MAX + 1))


# ----------------------------- list_favorites (no requiere Pro) ---------------

class TestListFavorites:
    def test_pro_con_favoritos(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[_row(id=1), _row(id=2)])
        resp = list_favorites(user=AuthUser(id="uid"))
        assert len(resp.favorites) == 2

    def test_ex_pro_puede_listar(self, monkeypatch, fake_pool, fake_conn):
        # Regla del código: list NO chequea has_active_subscription.
        # Ex-Pro con favoritos guardados puede seguir viéndolos.
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[_row()])
        # No monkeypatchamos has_active_subscription, pero list_favorites no lo invoca.
        resp = list_favorites(user=AuthUser(id="ex-pro"))
        assert len(resp.favorites) == 1

    def test_sin_favoritos(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[])
        resp = list_favorites(user=AuthUser(id="uid"))
        assert resp.favorites == []

    def test_query_filtra_por_clerk_user_id(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[])
        list_favorites(user=AuthUser(id="uid-test"))
        sql, params = fake_conn.executed[0]
        assert "clerk_user_id = %s" in sql
        assert params == ("uid-test",)

    def test_roundtrip_plan_data_a_pydantic(self, monkeypatch, fake_pool, fake_conn):
        # plan_data viene como dict (JSONB) → debe deserializarse a Plan correctamente.
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[_row(id=7)])
        resp = list_favorites(user=AuthUser(id="uid"))
        assert resp.favorites[0].plan.opciones[0].materia_codigo == 1
        assert resp.favorites[0].plan.opciones[0].cursos[0].id == 100

    def test_filters_data_se_deserializa(self, monkeypatch, fake_pool, fake_conn):
        filters_dict = FavoriteFilters(sedes_permitidas=["HY", "SI"]).model_dump(mode="json")
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[_row(id=8, filters_data=filters_dict)])
        resp = list_favorites(user=AuthUser(id="uid"))
        assert resp.favorites[0].filters is not None
        assert resp.favorites[0].filters.sedes_permitidas == ["HY", "SI"]

    def test_solo_con_cupos_sobrevive_el_roundtrip(self, monkeypatch, fake_pool, fake_conn):
        # Regresión: FavoriteFilters no declaraba solo_con_cupos, así que Pydantic
        # lo descartaba en silencio al guardar y el filtro nunca se persistía.
        filters_dict = FavoriteFilters(solo_con_cupos=True).model_dump(mode="json")
        assert filters_dict["solo_con_cupos"] is True
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[_row(filters_data=filters_dict)])
        resp = list_favorites(user=AuthUser(id="uid"))
        assert resp.favorites[0].filters.solo_con_cupos is True

    def test_nombre_y_descripcion_se_devuelven(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans",
                     rows=[_row(nombre="Cursada linda", descripcion="el que me cierra")])
        resp = list_favorites(user=AuthUser(id="uid"))
        assert resp.favorites[0].nombre == "Cursada linda"
        assert resp.favorites[0].descripcion == "el que me cierra"

    def test_favorito_viejo_sin_nombre_no_explota(self, monkeypatch, fake_pool, fake_conn):
        # Los favoritos guardados antes de la migración tienen ambas columnas en
        # NULL. Tienen que listarse igual: es el caso de los datos de prod.
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[_row(nombre=None, descripcion=None)])
        resp = list_favorites(user=AuthUser(id="uid"))
        assert resp.favorites[0].nombre is None
        assert resp.favorites[0].descripcion is None
        assert resp.favorites[0].plan.opciones[0].materia_codigo == 1

    def test_query_trae_las_columnas_nuevas(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("FROM favorite_plans", rows=[])
        list_favorites(user=AuthUser(id="uid"))
        sql, _ = fake_conn.executed[0]
        assert "nombre" in sql and "descripcion" in sql


# ----------------------------- delete_favorite --------------------------------

class TestDeleteFavorite:
    def test_id_propio_borra(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("DELETE FROM favorite_plans", rows=[], rowcount=1)
        resp = delete_favorite(favorite_id=5, user=AuthUser(id="uid"))
        assert resp == {"ok": True}
        assert fake_conn.commits == 1

    def test_id_inexistente_da_404(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("DELETE FROM favorite_plans", rows=[], rowcount=0)
        with pytest.raises(HTTPException) as exc:
            delete_favorite(favorite_id=999, user=AuthUser(id="uid"))
        assert exc.value.status_code == 404

    def test_id_de_otro_usuario_da_404(self, monkeypatch, fake_pool, fake_conn):
        # El WHERE incluye clerk_user_id → rowcount=0 → 404.
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("DELETE FROM favorite_plans", rows=[], rowcount=0)
        with pytest.raises(HTTPException) as exc:
            delete_favorite(favorite_id=1, user=AuthUser(id="otro-user"))
        assert exc.value.status_code == 404

    def test_query_incluye_clerk_user_id(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("DELETE FROM favorite_plans", rows=[], rowcount=1)
        delete_favorite(favorite_id=1, user=AuthUser(id="uid-X"))
        sql, params = fake_conn.executed[0]
        # WHERE id = %s AND clerk_user_id = %s
        assert "clerk_user_id = %s" in sql
        assert params == (1, "uid-X")

    def test_ex_pro_puede_borrar(self, monkeypatch, fake_pool, fake_conn):
        # delete_favorite no chequea has_active_subscription.
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("DELETE FROM favorite_plans", rows=[], rowcount=1)
        resp = delete_favorite(favorite_id=1, user=AuthUser(id="ex-pro"))
        assert resp == {"ok": True}


# ----------------------------- update_favorite (no requiere Pro) --------------

class TestUpdateFavorite:
    def test_id_propio_actualiza(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("UPDATE favorite_plans",
                     rows=[{"nombre": "Nuevo", "descripcion": "desc"}])
        resp = update_favorite(
            favorite_id=5,
            body=FavoriteUpdate(nombre="Nuevo", descripcion="desc"),
            user=AuthUser(id="uid"),
        )
        assert resp.nombre == "Nuevo"
        assert resp.descripcion == "desc"
        assert fake_conn.commits == 1

    def test_id_inexistente_da_404(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("UPDATE favorite_plans", rows=[])
        with pytest.raises(HTTPException) as exc:
            update_favorite(
                favorite_id=999, body=FavoriteUpdate(nombre="X"), user=AuthUser(id="uid")
            )
        assert exc.value.status_code == 404

    def test_id_de_otro_usuario_da_404(self, monkeypatch, fake_pool, fake_conn):
        # El WHERE incluye clerk_user_id → no matchea ninguna fila → 404.
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("UPDATE favorite_plans", rows=[])
        with pytest.raises(HTTPException) as exc:
            update_favorite(
                favorite_id=1, body=FavoriteUpdate(nombre="X"), user=AuthUser(id="otro-user")
            )
        assert exc.value.status_code == 404

    def test_query_incluye_clerk_user_id(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("UPDATE favorite_plans", rows=[{"nombre": "N", "descripcion": None}])
        update_favorite(
            favorite_id=1,
            body=FavoriteUpdate(nombre="N"),
            user=AuthUser(id="uid-X"),
        )
        sql, params = fake_conn.executed[0]
        assert "clerk_user_id = %s" in sql
        assert params == ("N", None, 1, "uid-X")

    def test_descripcion_none_limpia_el_campo(self, monkeypatch, fake_pool, fake_conn):
        # El UPDATE pisa descripcion, no la preserva: mandar null la borra.
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("UPDATE favorite_plans", rows=[{"nombre": "N", "descripcion": None}])
        resp = update_favorite(
            favorite_id=1,
            body=FavoriteUpdate(nombre="N", descripcion=None),
            user=AuthUser(id="uid"),
        )
        _, params = fake_conn.executed[0]
        assert params[1] is None
        assert resp.descripcion is None

    def test_ex_pro_puede_editar(self, monkeypatch, fake_pool, fake_conn):
        # update_favorite no chequea has_active_subscription: si lo invocara,
        # este test explotaría (no está monkeypatcheado y necesitaría DB real).
        def boom(conn, uid):
            raise AssertionError("update_favorite no debe chequear la suscripción")

        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        monkeypatch.setattr("api.favoritos.has_active_subscription", boom)
        fake_conn.on("UPDATE favorite_plans", rows=[{"nombre": "N", "descripcion": None}])
        resp = update_favorite(
            favorite_id=1, body=FavoriteUpdate(nombre="N"), user=AuthUser(id="ex-pro")
        )
        assert resp.nombre == "N"

    def test_nombre_se_trimea_antes_de_persistir(self, monkeypatch, fake_pool, fake_conn):
        monkeypatch.setattr("api.favoritos.pool", fake_pool)
        fake_conn.on("UPDATE favorite_plans", rows=[{"nombre": "N", "descripcion": None}])
        update_favorite(
            favorite_id=1,
            body=FavoriteUpdate(nombre="  Mi plan  "),
            user=AuthUser(id="uid"),
        )
        _, params = fake_conn.executed[0]
        assert params[0] == "Mi plan"
