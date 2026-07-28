"""Tests de las materias anuales en el scraper.

Cubren las dos cosas que las protegen: la exención del sweep (el SQL se verifica
contra FakeConn, que no ejecuta SQL, así que se chequea el predicado y los
params) y la guarda de `replace_cursos` ante un detalle vacío.
"""

from __future__ import annotations

import pytest

from scraper.config import MATERIAS_ANUALES
from scraper.db import (
    dar_de_baja_no_vistas,
    es_materia_anual,
    listar_a_dar_de_baja,
    listar_exentas_por_anual,
    marcar_oferta_congelada,
    replace_cursos,
    sync_materias_anuales,
)
from scraper.parse import CatedraDetalle, Curso


def _normalizar(sql: str) -> str:
    return " ".join(sql.lower().split())


def _detalle(catedra_id=1, materia_codigo=4, cursos=None) -> CatedraDetalle:
    return CatedraDetalle(
        catedra_id=catedra_id,
        cuatrimestre="1",
        numero="1",
        titular="Titular X",
        materia_codigo=materia_codigo,
        materia_nombre="Materia X",
        cursos=cursos or [],
    )


def _curso() -> Curso:
    return Curso(
        tipo="comision",
        codigo="1",
        dia="lunes",
        hora_inicio="10:00",
        hora_fin="12:00",
        profesor="Prof X",
        vacantes=30,
        obligatorio=None,
        aula="HY101",
        sede="HY",
        observaciones=None,
    )


class TestConfig:
    def test_hay_materias_anuales_configuradas(self):
        # La lista del código es la fuente de verdad del flag.
        assert len(MATERIAS_ANUALES) > 0
        assert all(isinstance(c, int) for c in MATERIAS_ANUALES)


class TestSyncMateriasAnuales:
    def test_manda_la_lista_como_param(self, fake_conn):
        fake_conn.on("update materias set anual", rowcount=2)
        assert sync_materias_anuales(fake_conn, (4, 16)) == 2
        sql, params = fake_conn.executed[0]
        assert params == {"ids": [4, 16]}

    def test_solo_escribe_lo_que_cambia(self, fake_conn):
        # Sin el WHERE, cada corrida reescribiría la tabla entera.
        fake_conn.on("update materias set anual", rowcount=0)
        sync_materias_anuales(fake_conn, (4, 16))
        sql = _normalizar(fake_conn.executed[0][0])
        assert "where anual <> (codigo = any(%(ids)s))" in sql

    def test_lista_vacia_desmarca_todo(self, fake_conn):
        fake_conn.on("update materias set anual", rowcount=2)
        sync_materias_anuales(fake_conn, ())
        assert fake_conn.executed[0][1] == {"ids": []}


class TestSweepExentas:
    """El sweep no puede apagar cátedras de una materia anual ausente del índice."""

    def test_update_excluye_anuales_ausentes(self, fake_conn):
        fake_conn.on("update catedras set vigente = false", rowcount=3)
        assert dar_de_baja_no_vistas(fake_conn, [1, 2, 3]) == 3
        sql = _normalizar(fake_conn.executed[0][0])
        assert "materia_codigo not in (select codigo from anuales_ausentes)" in sql
        # "Ausente" = ninguna de sus cátedras figura entre las vistas de esta corrida.
        assert "not exists" in sql
        assert "c.materia_codigo = m.codigo and c.id = any(%(vistas)s)" in sql

    def test_materia_anual_presente_en_el_indice_no_queda_exenta(self, fake_conn):
        # El CTE se define sobre las vistas de la corrida: si alguna cátedra de la
        # materia anual aparece, la materia no entra en `anuales_ausentes` y sus
        # otras cátedras se barren normal.
        fake_conn.on("update catedras set vigente = false", rowcount=1)
        dar_de_baja_no_vistas(fake_conn, [7])
        sql = _normalizar(fake_conn.executed[0][0])
        assert "where m.anual" in sql
        assert fake_conn.executed[0][1] == {"vistas": [7]}

    def test_lista_vacia_sigue_abortando(self, fake_conn):
        # Guarda vieja: con vistas vacías el UPDATE daría de baja toda la oferta.
        with pytest.raises(ValueError):
            dar_de_baja_no_vistas(fake_conn, [])
        assert fake_conn.executed == []

    def test_listar_a_dar_de_baja_usa_el_mismo_predicado(self, fake_conn):
        fake_conn.on("select ca.id, m.nombre", rows=[(1, "Materia X")])
        assert listar_a_dar_de_baja(fake_conn, [1, 2]) == [(1, "Materia X")]
        sql = _normalizar(fake_conn.executed[0][0])
        assert "not in (select codigo from anuales_ausentes)" in sql

    def test_listar_exentas_es_el_complemento(self, fake_conn):
        fake_conn.on("select ca.id, m.nombre", rows=[(9, "Psicopatología")])
        assert listar_exentas_por_anual(fake_conn, [1, 2]) == [(9, "Psicopatología")]
        sql = _normalizar(fake_conn.executed[0][0])
        assert "materia_codigo in (select codigo from anuales_ausentes)" in sql

    def test_listar_exentas_con_vistas_vacias_no_consulta(self, fake_conn):
        assert listar_exentas_por_anual(fake_conn, []) == []
        assert fake_conn.executed == []


class TestOfertaCongelada:
    """El flag que le dice a `solo_con_cupos` que los cupos son del cuatrimestre
    anterior. Se deriva del mismo hecho que la exención del sweep."""

    def test_usa_el_mismo_predicado_que_la_exencion(self, fake_conn):
        fake_conn.on("update materias m", rowcount=2)
        assert marcar_oferta_congelada(fake_conn, [1, 2]) == 2
        sql = _normalizar(fake_conn.executed[0][0])
        assert "with anuales_ausentes as" in sql
        assert (
            "set oferta_congelada = (m.codigo in (select codigo from anuales_ausentes))"
            in sql
        )

    def test_solo_escribe_lo_que_cambia(self, fake_conn):
        fake_conn.on("update materias m", rowcount=0)
        marcar_oferta_congelada(fake_conn, [1])
        sql = _normalizar(fake_conn.executed[0][0])
        # Sin el WHERE cada corrida reescribiría las ~500 materias. Además, así se
        # apaga solo el flag de una materia que salió de MATERIAS_ANUALES: deja de
        # entrar en el CTE, el valor calculado le da FALSE y la fila se corrige.
        assert "where m.oferta_congelada <> (m.codigo in" in sql

    def test_lista_vacia_aborta(self, fake_conn):
        # Con vistas vacías el CTE daría "todas ausentes" y congelaría la oferta entera.
        with pytest.raises(ValueError):
            marcar_oferta_congelada(fake_conn, [])
        assert fake_conn.executed == []


class TestReplaceCursosMateriaAnual:
    """Si la fuente no trae horarios para una anual, los guardados se conservan."""

    def test_detalle_vacio_en_anual_no_borra(self, fake_conn):
        fake_conn.on("select anual from materias", rows=[(True,)])
        replace_cursos(fake_conn, _detalle(materia_codigo=4, cursos=[]))
        assert not any(
            "delete from cursos" in _normalizar(sql) for sql, _ in fake_conn.executed
        )

    def test_detalle_vacio_en_no_anual_si_borra(self, fake_conn):
        # Comportamiento de siempre: una cátedra común que se queda sin comisiones
        # se vacía, porque la próxima corrida la vuelve a traer.
        fake_conn.on("select anual from materias", rows=[(False,)])
        fake_conn.on("delete from cursos", rowcount=3)
        replace_cursos(fake_conn, _detalle(materia_codigo=99, cursos=[]))
        assert any(
            "delete from cursos" in _normalizar(sql) for sql, _ in fake_conn.executed
        )

    def test_detalle_con_cursos_en_anual_reemplaza(self, fake_conn):
        # Si la fuente sí trae datos, mandan los nuevos: no se consulta ni el flag.
        fake_conn.on("delete from cursos", rowcount=1)
        replace_cursos(fake_conn, _detalle(materia_codigo=4, cursos=[_curso()]))
        sqls = [_normalizar(sql) for sql, _ in fake_conn.executed]
        assert any("delete from cursos" in s for s in sqls)
        assert not any("select anual from materias" in s for s in sqls)


class TestEsMateriaAnual:
    def test_true(self, fake_conn):
        fake_conn.on("select anual from materias", rows=[(True,)])
        assert es_materia_anual(fake_conn, 4) is True

    def test_false(self, fake_conn):
        fake_conn.on("select anual from materias", rows=[(False,)])
        assert es_materia_anual(fake_conn, 99) is False

    def test_materia_inexistente(self, fake_conn):
        fake_conn.on("select anual from materias", rows=[])
        assert es_materia_anual(fake_conn, 12345) is False
