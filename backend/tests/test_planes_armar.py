"""Tests end-to-end de `armar_planes` con FakeConn.

Cubre cada filtro de PlanRequest / MateriaSeleccionada por separado y en
combinación. La DB se mockea con FakeConn — las filas se construyen con
make_comision_row / make_obliga_row de conftest.
"""

from __future__ import annotations

from datetime import time

import pytest

from api.planes import (
    FranjaExcluida,
    MateriaSeleccionada,
    PlanRequest,
    armar_planes,
)

from .conftest import make_comision_row, make_obliga_row, setup_planes_db


# ----------------------------- Helpers locales --------------------------------

def _req(materias, **overrides):
    base = {"materias": materias, "max_planes": 20}
    base.update(overrides)
    return PlanRequest(**base)


# ----------------------------- Casos base -------------------------------------

class TestVigencia:
    """El armado sólo puede usar cátedras vigentes.

    El filtrado ocurre en SQL, y FakeConn no ejecuta SQL: acá sólo se puede
    verificar que el predicado siga en el query. El filtrado real se prueba
    contra la DB local (ver la sección de verificación del README de backend).
    """

    def test_query_de_opciones_filtra_por_vigente(self, fake_conn):
        setup_planes_db(fake_conn, [
            make_comision_row(comision_id=100, materia_codigo=1, materia_nombre="M1",
                              catedra_id=10, dia="lunes",
                              hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ])
        armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)]))

        sql_opciones = next(
            sql for sql, _ in fake_conn.executed if "FROM materias m" in sql
        )
        normalizado = " ".join(sql_opciones.split())
        assert "JOIN catedras ca ON ca.materia_codigo = m.codigo AND ca.vigente" in normalizado


class TestBase:
    def test_happy_path_2x2_sin_conflictos(self, fake_conn):
        # 2 materias × 2 comisiones, en días distintos → 4 planes posibles.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, materia_nombre="M1",
                              catedra_id=10, dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=101, materia_codigo=1, materia_nombre="M1",
                              catedra_id=10, dia="lunes", hora_inicio=time(14, 0), hora_fin=time(16, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, materia_nombre="M2",
                              catedra_id=20, dia="martes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=201, materia_codigo=2, materia_nombre="M2",
                              catedra_id=20, dia="martes", hora_inicio=time(14, 0), hora_fin=time(16, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        req = _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)])
        resp = armar_planes(fake_conn, req)
        assert len(resp.planes) == 4
        assert resp.materias_sin_opciones == []
        assert resp.total_generados >= 4

    def test_solapamiento_descarta_combo(self, fake_conn):
        # 2 comisiones en mismo día/hora → solapan, no se generan planes para ese combo.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, materia_nombre="M1",
                              catedra_id=10, dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, materia_nombre="M2",
                              catedra_id=20, dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        req = _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)])
        resp = armar_planes(fake_conn, req)
        assert resp.planes == []
        assert resp.total_generados >= 1
        assert resp.materias_sin_opciones == []

    def test_materia_sin_comisiones_en_db(self, fake_conn):
        # Mat 1 tiene comisión, mat 2 no.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, materia_nombre="M1",
                              catedra_id=10, dia="lunes"),
        ]
        setup_planes_db(fake_conn, comisiones)
        req = _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)])
        resp = armar_planes(fake_conn, req)
        assert resp.planes == []
        assert 2 in resp.materias_sin_opciones

    def test_una_materia_una_comision(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, materia_nombre="M1",
                              catedra_id=10, dia="lunes"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 100

    def test_obligas_solapando_con_otra_materia_descarta_combo(self, fake_conn):
        # Comisión M1 ok, pero su teórico choca con la comisión M2.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, materia_nombre="M1",
                              catedra_id=10, dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, materia_nombre="M2",
                              catedra_id=20, dia="martes", hora_inicio=time(14, 0), hora_fin=time(16, 0)),
        ]
        obligas = [
            make_obliga_row(comision_id=100, obliga_id=1000, tipo="teorico", codigo="T1",
                            catedra_id=10, dia="martes", hora_inicio=time(14, 0), hora_fin=time(16, 0)),
        ]
        setup_planes_db(fake_conn, comisiones, obligas)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)]))
        assert resp.planes == []
        assert resp.materias_sin_opciones == []


# ----------------------------- Filtro: dias_excluidos -------------------------

class TestDiasExcluidos:
    def test_dia_unico_excluido_filtra_comisiones(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], dias_excluidos=["lunes"]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 101

    def test_multiples_dias_excluidos(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes"),
            make_comision_row(comision_id=102, materia_codigo=1, catedra_id=10, dia="miercoles"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1)], dias_excluidos=["lunes", "martes"]),
        )
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 102

    def test_dia_excluido_normalizado_a_lowercase(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes"),
        ]
        setup_planes_db(fake_conn, comisiones)
        # Input con mayúsculas debe normalizar a lowercase y matchear.
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], dias_excluidos=["LUNES"]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 101

    def test_dia_excluido_aplica_a_obligas(self, fake_conn):
        # Comisión OK, pero su teórico cae en día excluido → opción descartada.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
        ]
        obligas = [
            make_obliga_row(comision_id=100, obliga_id=1000, dia="miercoles", catedra_id=10),
        ]
        setup_planes_db(fake_conn, comisiones, obligas)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], dias_excluidos=["miercoles"]))
        assert resp.planes == []
        assert 1 in resp.materias_sin_opciones


# ----------------------------- Filtro: franjas_excluidas ----------------------

class TestFranjasExcluidas:
    def test_franja_que_solapa_descarta(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(16, 0), hora_fin=time(18, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        franja = FranjaExcluida(dias=["lunes"], hora_inicio=time(11, 0), hora_fin=time(13, 0))
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], franjas_excluidas=[franja]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 101

    def test_franja_adyacente_NO_descarta(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        franja = FranjaExcluida(dias=["lunes"], hora_inicio=time(12, 0), hora_fin=time(14, 0))
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], franjas_excluidas=[franja]))
        assert len(resp.planes) == 1

    def test_franja_otro_dia_no_descarta(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        franja = FranjaExcluida(dias=["martes"], hora_inicio=time(10, 0), hora_fin=time(14, 0))
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], franjas_excluidas=[franja]))
        assert len(resp.planes) == 1

    def test_multiples_franjas(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="martes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=102, materia_codigo=1, catedra_id=10,
                              dia="miercoles", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        franjas = [
            FranjaExcluida(dias=["lunes"], hora_inicio=time(9, 0), hora_fin=time(13, 0)),
            FranjaExcluida(dias=["martes"], hora_inicio=time(9, 0), hora_fin=time(13, 0)),
        ]
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], franjas_excluidas=franjas))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 102

    def test_franja_aplica_a_obligas(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        obligas = [
            make_obliga_row(comision_id=100, obliga_id=1000, catedra_id=10,
                            dia="miercoles", hora_inicio=time(14, 0), hora_fin=time(16, 0)),
        ]
        setup_planes_db(fake_conn, comisiones, obligas)
        franja = FranjaExcluida(dias=["miercoles"], hora_inicio=time(15, 0), hora_fin=time(17, 0))
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], franjas_excluidas=[franja]))
        assert resp.planes == []
        assert 1 in resp.materias_sin_opciones


# ----------------------------- Filtro: sedes_permitidas -----------------------

class TestSedesPermitidas:
    def test_filtra_por_sede(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", sede="HY"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="lunes", sede="AV"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], sedes_permitidas=["HY"]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 100

    def test_lista_vacia_no_filtra(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", sede="HY"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", sede="AV"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], sedes_permitidas=[]))
        assert len(resp.planes) == 2

    def test_sede_none_en_curso_no_se_descarta(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", sede=None),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], sedes_permitidas=["HY"]))
        assert len(resp.planes) == 1

    def test_aplica_a_obligas(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", sede="HY"),
        ]
        obligas = [
            make_obliga_row(comision_id=100, obliga_id=1000, catedra_id=10, dia="martes", sede="AV"),
        ]
        setup_planes_db(fake_conn, comisiones, obligas)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], sedes_permitidas=["HY"]))
        assert resp.planes == []
        assert 1 in resp.materias_sin_opciones


# ----------------------------- Filtro: sede por materia (override) -----------

class TestSedePorMateria:
    def test_override_sede_por_materia(self, fake_conn):
        # Global permite HY+SI, pero la materia 1 quiere AV → solo opciones de AV.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", sede="HY"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", sede="AV"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req(
                [MateriaSeleccionada(codigo=1, sede="AV")],
                sedes_permitidas=["HY", "SI"],
            ),
        )
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 101

    def test_otra_materia_sin_override_usa_global(self, fake_conn):
        comisiones = [
            # M1 con sede="AV" (override), M2 sin override → usa global HY.
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", sede="AV"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="lunes", sede="HY"),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20, dia="martes", sede="HY"),
            make_comision_row(comision_id=201, materia_codigo=2, catedra_id=20, dia="martes", sede="AV"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req(
                [
                    MateriaSeleccionada(codigo=1, sede="AV"),
                    MateriaSeleccionada(codigo=2),
                ],
                sedes_permitidas=["HY"],
            ),
        )
        # M1 → solo AV (100); M2 → solo HY (200). 1 combo.
        assert len(resp.planes) == 1
        ids = sorted(op.cursos[0].id for op in resp.planes[0].opciones)
        assert ids == [100, 200]


# ----------------------------- Filtro: catedra_id -----------------------------

class TestCatedraId:
    def test_restringe_a_catedra(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
            make_comision_row(comision_id=200, materia_codigo=1, catedra_id=20, dia="martes"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, catedra_id=10)]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].catedra_id == 10

    def test_catedra_id_inexistente_da_materia_sin_opciones(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, catedra_id=999)]))
        assert resp.planes == []
        assert 1 in resp.materias_sin_opciones


# ----------------------------- Filtro: profesores (semántica triple) ----------

class TestProfesores:
    def _setup_dos_profes(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", profesor="Alice"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="martes", profesor="Bob"),
        ]
        setup_planes_db(fake_conn, comisiones)

    def test_none_no_filtra(self, fake_conn):
        self._setup_dos_profes(fake_conn)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, profesores=None)]))
        assert len(resp.planes) == 2

    def test_lista_vacia_da_cero_opciones(self, fake_conn):
        self._setup_dos_profes(fake_conn)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, profesores=[])]))
        assert resp.planes == []
        assert 1 in resp.materias_sin_opciones

    def test_un_solo_profesor(self, fake_conn):
        self._setup_dos_profes(fake_conn)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, profesores=["Alice"])]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].profesor == "Alice"

    def test_multiples_profesores_or(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", profesor="Alice"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", profesor="Bob"),
            make_comision_row(comision_id=102, materia_codigo=1, catedra_id=10, dia="miercoles", profesor="Carol"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, profesores=["Alice", "Carol"])]))
        ids = sorted(p.opciones[0].cursos[0].id for p in resp.planes)
        assert ids == [100, 102]

    def test_profesor_inexistente(self, fake_conn):
        self._setup_dos_profes(fake_conn)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, profesores=["NoExiste"])]))
        assert resp.planes == []
        assert 1 in resp.materias_sin_opciones

    def test_profesor_aplica_solo_a_comision_no_a_teorico(self, fake_conn):
        # Comisión profe Alice, teórico profe Z. Filtrar por Alice debe conservar.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", profesor="Alice"),
        ]
        obligas = [
            make_obliga_row(comision_id=100, obliga_id=1000, catedra_id=10,
                            tipo="teorico", dia="martes", profesor="Zeta"),
        ]
        setup_planes_db(fake_conn, comisiones, obligas)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1, profesores=["Alice"])]))
        assert len(resp.planes) == 1


# ----------------------------- Filtro: solo_con_cupos -------------------------

class TestSoloConCupos:
    def test_vacantes_none_descarta(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", vacantes=None),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", vacantes=10),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], solo_con_cupos=True))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 101

    def test_vacantes_cero_descarta(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", vacantes=0),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", vacantes=5),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], solo_con_cupos=True))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].vacantes == 5

    def test_off_no_filtra(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", vacantes=None),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", vacantes=0),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], solo_con_cupos=False))
        assert len(resp.planes) == 2

    def test_teoricos_con_vacantes_none_no_descartan(self, fake_conn):
        # Teórico con vacantes=None NO debe descartar la opción (comparte cupo vía comision_obliga).
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", vacantes=10),
        ]
        obligas = [
            make_obliga_row(comision_id=100, obliga_id=1000, catedra_id=10, dia="martes", vacantes=None),
        ]
        setup_planes_db(fake_conn, comisiones, obligas)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)], solo_con_cupos=True))
        assert len(resp.planes) == 1


# ----------------------------- Filtro: max_bache_horas ------------------------

class TestMaxBacheHoras:
    def test_dias_distintos_siempre_pasa(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="martes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_bache_horas=0.5),
        )
        assert len(resp.planes) == 1

    def test_gap_grande_descarta_plan(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(16, 0), hora_fin=time(18, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_bache_horas=2.0),
        )
        # Gap de 6h > 2h → descartado.
        assert resp.planes == []

    def test_gap_dentro_del_max_pasa(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(11, 0), hora_fin=time(13, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_bache_horas=1.0),
        )
        assert len(resp.planes) == 1

    def test_none_no_filtra(self, fake_conn):
        # Sin max_bache_horas, un plan con gap enorme pasa.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(18, 0), hora_fin=time(20, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_bache_horas=None),
        )
        assert len(resp.planes) == 1


# ----------------------------- Filtro: min/max días por semana ----------------

class TestMinMaxDiasSemana:
    def _scenario_2x2(self, fake_conn):
        # M1: lunes(100) / martes(101). M2: lunes(200) / martes(201).
        # Horarios sin solapar dentro de un mismo día.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="martes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(14, 0), hora_fin=time(16, 0)),
            make_comision_row(comision_id=201, materia_codigo=2, catedra_id=20,
                              dia="martes", hora_inicio=time(14, 0), hora_fin=time(16, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)

    def test_dentro_del_rango_pasa(self, fake_conn):
        # Plan de 2 materias en días distintos → 2 días, dentro de [2, 3].
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20, dia="martes"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)],
                 min_dias_semana=2, max_dias_semana=3),
        )
        assert len(resp.planes) == 1

    def test_max_dias_descarta_combos_con_mas_dias(self, fake_conn):
        self._scenario_2x2(fake_conn)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_dias_semana=1),
        )
        # Solo sobreviven combos que caen todos en un mismo día.
        ids = sorted(tuple(sorted(op.cursos[0].id for op in p.opciones)) for p in resp.planes)
        assert ids == [(100, 200), (101, 201)]

    def test_min_dias_descarta_combos_con_menos_dias(self, fake_conn):
        self._scenario_2x2(fake_conn)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], min_dias_semana=2),
        )
        # Solo sobreviven combos repartidos en 2 días distintos.
        ids = sorted(tuple(sorted(op.cursos[0].id for op in p.opciones)) for p in resp.planes)
        assert ids == [(100, 201), (101, 200)]

    def test_min_igual_max_exacto(self, fake_conn):
        self._scenario_2x2(fake_conn)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)],
                 min_dias_semana=2, max_dias_semana=2),
        )
        ids = sorted(tuple(sorted(op.cursos[0].id for op in p.opciones)) for p in resp.planes)
        assert ids == [(100, 201), (101, 200)]

    def test_none_no_filtra(self, fake_conn):
        self._scenario_2x2(fake_conn)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)]),
        )
        assert len(resp.planes) == 4


# ----------------------------- Filtro: min/max horas por día ------------------

class TestMinMaxHorasDia:
    def test_span_incluye_huecos_supera_max_descarta(self, fake_conn):
        # Mismo día: 8-10 y 16-18 → span = 10h (la suma de duraciones sería 4h).
        # Con max=6 debe descartar: confirma semántica de span, no de suma.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(16, 0), hora_fin=time(18, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_horas_dia=6.0),
        )
        assert resp.planes == []

    def test_span_dentro_del_rango_pasa(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(16, 0), hora_fin=time(18, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)],
                 min_horas_dia=2.0, max_horas_dia=12.0),
        )
        assert len(resp.planes) == 1

    def test_span_menor_al_min_descarta(self, fake_conn):
        # Un solo bloque de 2h → span 2h; min=4 lo descarta.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1)], min_horas_dia=4.0),
        )
        assert resp.planes == []

    def test_cada_dia_se_evalua_por_separado(self, fake_conn):
        # Dos días con span 2h cada uno; max=3 → pasa (no se suma entre días).
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="martes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_horas_dia=3.0),
        )
        assert len(resp.planes) == 1

    def test_none_no_filtra(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(18, 0), hora_fin=time(20, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)]),
        )
        assert len(resp.planes) == 1


# ----------------------------- Filtro: max_planes (cap) -----------------------

class TestMaxPlanes:
    def test_capea_resultados(self, fake_conn):
        # 4 × 4 = 16 combos posibles, max_planes=3 → 3 planes.
        comisiones = []
        for cid, dia, hi in [
            (100, "lunes", 8), (101, "lunes", 10), (102, "lunes", 14), (103, "lunes", 16),
        ]:
            comisiones.append(make_comision_row(
                comision_id=cid, materia_codigo=1, catedra_id=10,
                dia=dia, hora_inicio=time(hi, 0), hora_fin=time(hi + 1, 0),
            ))
        for cid, dia, hi in [
            (200, "martes", 8), (201, "martes", 10), (202, "martes", 14), (203, "martes", 16),
        ]:
            comisiones.append(make_comision_row(
                comision_id=cid, materia_codigo=2, catedra_id=20,
                dia=dia, hora_inicio=time(hi, 0), hora_fin=time(hi + 1, 0),
            ))
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_planes=3),
        )
        assert len(resp.planes) == 3
        assert resp.total_generados >= 3

    def test_round_robin_rota_materia_cambiante_con_4_materias(self, fake_conn):
        # Regresión: con suficientes materias y cátedras, el enumerador debe
        # producir un pool con variación en TODAS las materias para que el
        # reorder round-robin alterne la materia que cambia entre planes
        # consecutivos (no que siempre cambie la última).
        # Caso del bug: con DFS lex el pool de 80 combos eran todos m0=0,
        # entonces sólo m3 (última materia) cambiaba.
        comisiones = []
        materias_data = [
            (1, 10, "lunes"),
            (2, 20, "martes"),
            (3, 30, "miercoles"),
            (4, 40, "jueves"),
        ]
        # 5 cátedras por materia → 5^4 = 625 combos, target_pool=80 lejos
        # del límite donde DFS lex llegaría a variar m0.
        for mat_cod, cat_id, dia in materias_data:
            for k in range(5):
                comisiones.append(make_comision_row(
                    comision_id=cat_id * 10 + k,
                    materia_codigo=mat_cod,
                    catedra_id=cat_id,
                    dia=dia,
                    hora_inicio=time(8 + k * 2, 0),
                    hora_fin=time(9 + k * 2, 0),
                ))
        setup_planes_db(fake_conn, comisiones)
        req = _req(
            [MateriaSeleccionada(codigo=c) for c, _, _ in materias_data],
            max_planes=8,
        )
        resp = armar_planes(fake_conn, req)

        assert len(resp.planes) == 8

        materias_que_cambian: set[int] = set()
        for i in range(len(resp.planes) - 1):
            p1, p2 = resp.planes[i], resp.planes[i + 1]
            for idx, (a, b) in enumerate(zip(p1.opciones, p2.opciones)):
                if a.cursos[0].id != b.cursos[0].id:
                    materias_que_cambian.add(idx)

        # En 8 planes consecutivos deberían variar al menos 3 de las 4
        # materias. Con el bug, sólo cambiaba 1 (la última).
        assert len(materias_que_cambian) >= 3, (
            f"Solo cambian las materias {materias_que_cambian} en los 8 "
            f"planes; se espera variación en ≥3 de las 4. Probable regresión "
            f"en diversidad del pool del enumerador."
        )

    def test_round_robin_varia_materias_en_los_primeros(self, fake_conn):
        # Garantía: los primeros N planes no solo cambian la última materia.
        comisiones = []
        for cid in (100, 101, 102, 103):
            comisiones.append(make_comision_row(
                comision_id=cid, materia_codigo=1, catedra_id=10,
                dia="lunes", hora_inicio=time(cid - 92, 0), hora_fin=time(cid - 91, 0),
            ))
        for cid in (200, 201, 202, 203):
            comisiones.append(make_comision_row(
                comision_id=cid, materia_codigo=2, catedra_id=20,
                dia="martes", hora_inicio=time(cid - 192, 0), hora_fin=time(cid - 191, 0),
            ))
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], max_planes=4),
        )
        # Entre plan[0] y plan[1] debería cambiar M1 (target=0). Entre plan[1] y plan[2], M2.
        # Mínimo: no todos los planes pueden tener la misma opción de M1.
        m1_ids = {p.opciones[0].cursos[0].id for p in resp.planes}
        assert len(m1_ids) > 1


# ----------------------------- Combinaciones cross-filter ---------------------

class TestCombinaciones:
    def test_franjas_y_sedes(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0), sede="HY"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(16, 0), hora_fin=time(18, 0), sede="AV"),
            make_comision_row(comision_id=102, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(16, 0), hora_fin=time(18, 0), sede="HY"),
        ]
        setup_planes_db(fake_conn, comisiones)
        franja = FranjaExcluida(dias=["lunes"], hora_inicio=time(9, 0), hora_fin=time(13, 0))
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1)], franjas_excluidas=[franja], sedes_permitidas=["HY"]),
        )
        # 100 cae en franja (descarta), 101 no es HY (descarta), 102 ok.
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 102

    def test_dias_catedra_profesores_combinados(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", profesor="Alice"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", profesor="Alice"),
            make_comision_row(comision_id=102, materia_codigo=1, catedra_id=10, dia="martes", profesor="Bob"),
            make_comision_row(comision_id=103, materia_codigo=1, catedra_id=20, dia="martes", profesor="Alice"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req(
                [MateriaSeleccionada(codigo=1, catedra_id=10, profesores=["Alice"])],
                dias_excluidos=["lunes"],
            ),
        )
        # Solo 101 cumple: catedra 10 + profesor Alice + no lunes.
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 101

    def test_override_sede_dentro_de_filtros_combinados(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", sede="AV", profesor="Alice"),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="lunes", sede="HY", profesor="Alice"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req(
                [MateriaSeleccionada(codigo=1, sede="AV", profesores=["Alice"])],
                sedes_permitidas=["HY", "SI"],
            ),
        )
        # Override pone AV; global no aplica.
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].id == 100

    def test_solo_con_cupos_mas_franja_mas_bache(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0), vacantes=10),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(14, 0), hora_fin=time(16, 0), vacantes=0),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(13, 0), hora_fin=time(15, 0), vacantes=5),
            make_comision_row(comision_id=201, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(17, 0), hora_fin=time(19, 0), vacantes=5),
        ]
        setup_planes_db(fake_conn, comisiones)
        franja = FranjaExcluida(dias=["lunes"], hora_inicio=time(15, 30), hora_fin=time(16, 30))
        resp = armar_planes(
            fake_conn,
            _req(
                [MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)],
                solo_con_cupos=True,
                franjas_excluidas=[franja],
                max_bache_horas=2.0,
            ),
        )
        # M1: 100 (10-12, vac=10) sobrevive; 101 descarta por vacantes=0.
        # M2: 200 (13-15) sobrevive (no choca franja 15:30-16:30); 201 (17-19) descarta por franja? No, 17-19 vs 15:30-16:30 no solapan. Pasa también.
        # Combo (100, 200): mismo día, gap 1h, bache OK → ✓
        # Combo (100, 201): mismo día, gap 5h > 2h → ✗
        ids = sorted(tuple(sorted(op.cursos[0].id for op in p.opciones)) for p in resp.planes)
        assert ids == [(100, 200)]

    def test_max_dias_mas_franja_mas_cupos(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0), vacantes=10),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10,
                              dia="martes", hora_inicio=time(10, 0), hora_fin=time(12, 0), vacantes=10),
            make_comision_row(comision_id=102, materia_codigo=1, catedra_id=10,
                              dia="lunes", hora_inicio=time(8, 0), hora_fin=time(9, 0), vacantes=10),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(14, 0), hora_fin=time(16, 0), vacantes=5),
            make_comision_row(comision_id=201, materia_codigo=2, catedra_id=20,
                              dia="lunes", hora_inicio=time(17, 0), hora_fin=time(19, 0), vacantes=0),
        ]
        setup_planes_db(fake_conn, comisiones)
        franja = FranjaExcluida(dias=["lunes"], hora_inicio=time(7, 30), hora_fin=time(9, 30))
        resp = armar_planes(
            fake_conn,
            _req(
                [MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)],
                franjas_excluidas=[franja],
                solo_con_cupos=True,
                max_dias_semana=1,
            ),
        )
        # M1: 102 cae en franja (descarta); quedan 100 (lunes) y 101 (martes).
        # M2: 201 sin cupos (descarta); queda 200 (lunes).
        # Combos: (100,200) → 1 día ✓; (101,200) → 2 días ✗ por max_dias=1.
        ids = sorted(tuple(sorted(op.cursos[0].id for op in p.opciones)) for p in resp.planes)
        assert ids == [(100, 200)]

    def test_short_circuit_cuando_una_materia_queda_sin_opciones(self, fake_conn):
        # Si M2 queda sin opciones, no debería intentar enumerar combos.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20, dia="lunes", sede="AV"),
        ]
        setup_planes_db(fake_conn, comisiones)
        resp = armar_planes(
            fake_conn,
            _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)], sedes_permitidas=["HY"]),
        )
        assert resp.planes == []
        assert 2 in resp.materias_sin_opciones
        # M1 también puede caer en materias_sin_opciones si su sede no es HY:
        # make_comision_row default es sede="HY", entonces M1 sí pasa.
        assert 1 not in resp.materias_sin_opciones


# ----------------------------- Determinismo / invariantes ---------------------

class TestDeterminismo:
    def test_mismas_inputs_misma_salida(self, fake_conn):
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=101, materia_codigo=1, catedra_id=10, dia="martes", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=200, materia_codigo=2, catedra_id=20, dia="miercoles", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
            make_comision_row(comision_id=201, materia_codigo=2, catedra_id=20, dia="jueves", hora_inicio=time(10, 0), hora_fin=time(12, 0)),
        ]
        setup_planes_db(fake_conn, comisiones)
        req = _req([MateriaSeleccionada(codigo=1), MateriaSeleccionada(codigo=2)])
        a = armar_planes(fake_conn, req)

        fake_conn2 = type(fake_conn)()
        setup_planes_db(fake_conn2, comisiones)
        b = armar_planes(fake_conn2, req)

        assert [
            [op.cursos[0].id for op in p.opciones] for p in a.planes
        ] == [
            [op.cursos[0].id for op in p.opciones] for p in b.planes
        ]

    def test_comision_es_siempre_el_primer_curso(self, fake_conn):
        # Invariante de _opcion_key: cursos[0] es la comisión.
        comisiones = [
            make_comision_row(comision_id=100, materia_codigo=1, catedra_id=10, dia="lunes"),
        ]
        obligas = [
            make_obliga_row(comision_id=100, obliga_id=1000, catedra_id=10, dia="martes", tipo="teorico"),
            make_obliga_row(comision_id=100, obliga_id=1001, catedra_id=10, dia="miercoles", tipo="seminario"),
        ]
        setup_planes_db(fake_conn, comisiones, obligas)
        resp = armar_planes(fake_conn, _req([MateriaSeleccionada(codigo=1)]))
        assert len(resp.planes) == 1
        assert resp.planes[0].opciones[0].cursos[0].tipo == "comision"
        assert resp.planes[0].opciones[0].cursos[0].id == 100
