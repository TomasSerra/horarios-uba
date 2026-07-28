"""Tests del gating Pro: _request_uses_filters + endpoint /planes."""

from __future__ import annotations

from datetime import time

import pytest
from fastapi import HTTPException

from api.auth import AuthUser
from api.main import _request_uses_filters, post_planes
from api.planes import FranjaExcluida, MateriaSeleccionada, PlanRequest

from .conftest import make_comision_row, setup_planes_db


def _req(materias=None, **overrides):
    base = {"materias": materias or [MateriaSeleccionada(codigo=1)], "max_planes": 20}
    base.update(overrides)
    return PlanRequest(**base)


def _uses(req, anuales=()):
    """Por defecto ninguna materia es anual: el caso más común y el más restrictivo."""
    return _request_uses_filters(req, set(anuales))


# ----------------------------- _request_uses_filters --------------------------

class TestRequestUsesFilters:
    def test_request_minimo_no_es_pro(self):
        assert _uses(_req()) is False

    def test_franjas_excluidas_dispara(self):
        franja = FranjaExcluida(dias=["lunes"], hora_inicio=time(10, 0), hora_fin=time(12, 0))
        assert _uses(_req(franjas_excluidas=[franja])) is True

    def test_sedes_permitidas_dispara(self):
        assert _uses(_req(sedes_permitidas=["HY"])) is True

    def test_max_bache_horas_dispara(self):
        assert _uses(_req(max_bache_horas=2.0)) is True

    def test_max_bache_horas_cero_dispara(self):
        # max_bache_horas=0 NO es None → cuenta como filtro Pro.
        assert _uses(_req(max_bache_horas=0.0)) is True

    def test_catedra_id_por_materia_dispara(self):
        assert _uses(_req([MateriaSeleccionada(codigo=1, catedra_id=10)])) is True

    def test_profesores_none_no_dispara(self):
        # None = sin filtro → no es feature Pro.
        assert _uses(_req([MateriaSeleccionada(codigo=1, profesores=None)])) is False

    def test_profesores_lista_vacia_dispara(self):
        assert _uses(_req([MateriaSeleccionada(codigo=1, profesores=[])])) is True

    def test_profesores_con_valor_dispara(self):
        assert _uses(_req([MateriaSeleccionada(codigo=1, profesores=["Alice"])])) is True

    def test_sede_por_materia_dispara(self):
        assert _uses(_req([MateriaSeleccionada(codigo=1, sede="HY")])) is True

    def test_min_dias_semana_dispara(self):
        assert _uses(_req(min_dias_semana=2)) is True

    def test_max_dias_semana_dispara(self):
        assert _uses(_req(max_dias_semana=4)) is True

    def test_min_horas_dia_dispara(self):
        assert _uses(_req(min_horas_dia=2.0)) is True

    def test_max_horas_dia_dispara(self):
        assert _uses(_req(max_horas_dia=6.0)) is True

    def test_dias_excluidos_NO_dispara(self):
        # Free feature: el FE permite excluir días sin ser Pro.
        assert _uses(_req(dias_excluidos=["lunes", "sabado"])) is False

    def test_solo_con_cupos_NO_dispara(self):
        assert _uses(_req(solo_con_cupos=True)) is False

    def test_max_planes_NO_dispara(self):
        assert _uses(_req(max_planes=80)) is False

    def test_una_materia_con_filtros_alcanza(self):
        # Si UNA de las materias tiene un filtro Pro, todo el request es Pro.
        materias = [
            MateriaSeleccionada(codigo=1),
            MateriaSeleccionada(codigo=2, catedra_id=20),
        ]
        assert _uses(_req(materias)) is True


class TestMateriasAnuales:
    """En materias anuales cátedra y comisión son gratis: el alumno ya está
    cursando una comisión concreta y necesita bloquear ese horario."""

    def test_catedra_en_materia_anual_no_dispara(self):
        req = _req([MateriaSeleccionada(codigo=4, catedra_id=10)])
        assert _uses(req, anuales={4}) is False

    def test_comision_en_materia_anual_no_dispara(self):
        req = _req([MateriaSeleccionada(codigo=4, catedra_id=10, comision_codigo="1")])
        assert _uses(req, anuales={4}) is False

    def test_comision_en_materia_no_anual_dispara(self):
        req = _req([MateriaSeleccionada(codigo=7, catedra_id=10, comision_codigo="1")])
        assert _uses(req, anuales={4}) is True

    def test_profesores_en_materia_anual_igual_dispara(self):
        # La exención cubre cátedra y comisión, no profesores.
        req = _req([MateriaSeleccionada(codigo=4, profesores=["Alice"])])
        assert _uses(req, anuales={4}) is True

    def test_sede_en_materia_anual_igual_dispara(self):
        req = _req([MateriaSeleccionada(codigo=4, sede="HY")])
        assert _uses(req, anuales={4}) is True

    def test_filtro_global_con_materia_anual_igual_dispara(self):
        # La exención es por materia; los filtros globales siguen siendo Pro.
        req = _req([MateriaSeleccionada(codigo=4, catedra_id=10)], sedes_permitidas=["HY"])
        assert _uses(req, anuales={4}) is True

    def test_mezcla_anual_y_no_anual(self):
        materias = [
            MateriaSeleccionada(codigo=4, catedra_id=10),
            MateriaSeleccionada(codigo=7, catedra_id=20),
        ]
        assert _uses(_req(materias), anuales={4}) is True


# ----------------------------- /planes endpoint gating -------------------------

# Para testear post_planes necesitamos parchear `pool` con un FakePool y `has_active_subscription`
# con un stub. Hacemos esto via monkeypatch en cada test.

def _setup_pool_and_sub(
    monkeypatch, fake_pool, fake_conn, *, has_sub: bool, anuales=(), comision_rows=None
):
    monkeypatch.setattr("api.main.pool", fake_pool)
    monkeypatch.setattr("api.main.has_active_subscription", lambda conn, uid: has_sub)
    # Lookup de materias anuales (sólo se ejecuta para no-Pro con cátedra/comisión).
    fake_conn.on("where anual and codigo", rows=[{"codigo": c} for c in anuales])
    # _fetch_opciones_por_materia hace 2 queries; cargamos respuestas mínimas.
    setup_planes_db(fake_conn, comision_rows or [
        make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
    ])


class TestPlanesEndpointGating:
    def test_anonimo_sin_filtros_pasa_capeado_a_15(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(max_planes=50)
        resp = post_planes(req, user=None)
        # Debe haber capeado a 15.
        assert req.max_planes == 15
        assert len(resp.planes) <= 15

    def test_anonimo_con_filtros_da_403(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(sedes_permitidas=["HY"])
        with pytest.raises(HTTPException) as exc:
            post_planes(req, user=None)
        assert exc.value.status_code == 403
        assert "Pro" in exc.value.detail

    def test_anonimo_con_min_dias_semana_da_403(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(min_dias_semana=2)
        with pytest.raises(HTTPException) as exc:
            post_planes(req, user=None)
        assert exc.value.status_code == 403

    def test_anonimo_con_max_horas_dia_da_403(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(max_horas_dia=6.0)
        with pytest.raises(HTTPException) as exc:
            post_planes(req, user=None)
        assert exc.value.status_code == 403

    def test_pro_con_dias_horas_pasa(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=True)
        req = _req(min_dias_semana=1, max_dias_semana=3, min_horas_dia=1.0, max_horas_dia=8.0)
        resp = post_planes(req, user=AuthUser(id="uid-pro"))
        assert resp is not None

    def test_free_logueado_sin_filtros_pasa(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req()
        resp = post_planes(req, user=AuthUser(id="uid-free"))
        assert resp.planes  # se generó al menos uno

    def test_free_logueado_con_filtros_da_403(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(franjas_excluidas=[FranjaExcluida(dias=["lunes"], hora_inicio=time(9, 0), hora_fin=time(11, 0))])
        with pytest.raises(HTTPException) as exc:
            post_planes(req, user=AuthUser(id="uid-free"))
        assert exc.value.status_code == 403

    def test_pro_sin_filtros_pasa_con_cap_100(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=True)
        req = _req(max_planes=80)
        post_planes(req, user=AuthUser(id="uid-pro"))
        assert req.max_planes == 80

    def test_pro_con_filtros_pasa(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=True)
        req = _req(sedes_permitidas=["HY"], franjas_excluidas=[
            FranjaExcluida(dias=["sabado"], hora_inicio=time(9, 0), hora_fin=time(11, 0))
        ])
        resp = post_planes(req, user=AuthUser(id="uid-pro"))
        assert resp is not None

    def test_pro_con_max_planes_excedido_mutila_a_100(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=True)
        # PlanRequest tiene Field(20, ge=1, le=100), así que max=100 es el techo de Pydantic.
        # Pasar 100 (el cap de Pro) → no se modifica.
        req = _req(max_planes=100)
        post_planes(req, user=AuthUser(id="uid-pro"))
        assert req.max_planes == 100

    def test_free_con_max_planes_excedido_se_mutila_a_15(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(max_planes=99)
        post_planes(req, user=AuthUser(id="uid-free"))
        assert req.max_planes == 15

    def test_anonimo_con_profesores_lista_vacia_da_403(self, monkeypatch, fake_pool, fake_conn):
        # profesores=[] es feature Pro (semántica triple).
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req([MateriaSeleccionada(codigo=1, profesores=[])])
        with pytest.raises(HTTPException) as exc:
            post_planes(req, user=None)
        assert exc.value.status_code == 403

    def test_anonimo_con_dias_excluidos_pasa(self, monkeypatch, fake_pool, fake_conn):
        # dias_excluidos no es Pro → debería pasar para anónimo.
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(dias_excluidos=["sabado"])
        resp = post_planes(req, user=None)
        assert resp is not None

    def test_anonimo_con_solo_con_cupos_pasa(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        req = _req(solo_con_cupos=True)
        resp = post_planes(req, user=None)
        assert resp is not None

    def test_anonimo_con_catedra_en_materia_anual_pasa(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(
            monkeypatch, fake_pool, fake_conn, has_sub=False, anuales=(4,),
            comision_rows=[make_comision_row(comision_id=100, materia_codigo=4, catedra_id=10)],
        )
        req = _req([MateriaSeleccionada(codigo=4, catedra_id=10)])
        resp = post_planes(req, user=None)
        assert resp.planes

    def test_anonimo_con_comision_en_materia_anual_pasa(self, monkeypatch, fake_pool, fake_conn):
        _setup_pool_and_sub(
            monkeypatch, fake_pool, fake_conn, has_sub=False, anuales=(4,),
            comision_rows=[
                make_comision_row(comision_id=100, comision_codigo="1",
                                  materia_codigo=4, catedra_id=10),
                make_comision_row(comision_id=101, comision_codigo="2",
                                  materia_codigo=4, catedra_id=10, dia="martes"),
            ],
        )
        req = _req([MateriaSeleccionada(codigo=4, catedra_id=10, comision_codigo="2")])
        resp = post_planes(req, user=None)
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].codigo == "2"

    def test_anonimo_con_catedra_en_materia_no_anual_da_403(self, monkeypatch, fake_pool, fake_conn):
        # Misma request pero la materia no está marcada como anual.
        _setup_pool_and_sub(
            monkeypatch, fake_pool, fake_conn, has_sub=False, anuales=(),
            comision_rows=[make_comision_row(comision_id=100, materia_codigo=4, catedra_id=10)],
        )
        req = _req([MateriaSeleccionada(codigo=4, catedra_id=10)])
        with pytest.raises(HTTPException) as exc:
            post_planes(req, user=None)
        assert exc.value.status_code == 403

    def test_pro_no_consulta_materias_anuales(self, monkeypatch, fake_pool, fake_conn):
        # El lookup extra sólo debe pagarse cuando puede cambiar la decisión.
        _setup_pool_and_sub(
            monkeypatch, fake_pool, fake_conn, has_sub=True, anuales=(4,),
            comision_rows=[make_comision_row(comision_id=100, materia_codigo=4, catedra_id=10)],
        )
        post_planes(_req([MateriaSeleccionada(codigo=4, catedra_id=10)]),
                    user=AuthUser(id="uid-pro"))
        assert not any("anual" in sql.lower() for sql, _ in fake_conn.executed)

    def test_sin_catedra_ni_comision_no_consulta_materias_anuales(
        self, monkeypatch, fake_pool, fake_conn
    ):
        _setup_pool_and_sub(monkeypatch, fake_pool, fake_conn, has_sub=False)
        post_planes(_req(), user=None)
        assert not any("anual" in sql.lower() for sql, _ in fake_conn.executed)
