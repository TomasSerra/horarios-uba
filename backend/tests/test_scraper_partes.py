"""Tests de las comisiones que la fuente publica en varias filas.

La fila principal trae el número, las vacantes y el `Oblig.`; las siguientes vienen
con la celda de código vacía y son otros encuentros de esa misma comisión. Al
anotarte te anotás a todos, así que tienen que viajar juntas hasta el plan.
"""

from __future__ import annotations

from datetime import time

from scraper.db import replace_cursos, resolve_obligatorio
from scraper.parse import CatedraDetalle, Curso, parse_catedra_page


def _normalizar(sql: str) -> str:
    return " ".join(sql.lower().split())


# Celdas: codigo, dia, inicio, fin, tipo, profesor, vac, oblig, aula, observ.
# Una fila con codigo="" es una continuación de la anterior.
def _pagina(comisiones=(), teoricos=(), catedra_id=574, materia_codigo=10359) -> str:
    def tabla(titulo, filas):
        if not filas:
            return ""
        cuerpo = "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in fila) + "</tr>" for fila in filas
        )
        return (
            f'<table class="table_tabs"><tr><th>{titulo}</th>'
            "<th>Dia</th><th>Inicio</th><th>Fin</th><th>Tipo</th><th>Profesor</th>"
            "<th>Vac.</th><th>Oblig.</th><th>Aula</th><th>Observ.</th></tr>"
            f"{cuerpo}</table>"
        )

    return (
        '<html><body><td class="option1">'
        f"2025/1 * Listado horarios de cátedra {catedra_id} - 1 - Titular X * "
        f"Materia ( {materia_codigo} - Materia X )"
        "</td>"
        + tabla("Teóricos", teoricos)
        + tabla("Comisiones", comisiones)
        + "</body></html>"
    )


def _comisiones(html: str) -> list[Curso]:
    detalle = parse_catedra_page(html)
    assert detalle is not None
    return [c for c in detalle.cursos if c.tipo == "comision"]


class TestParseoDePartes:
    def test_comision_de_dos_filas_es_un_curso_con_una_parte(self):
        # Caso de cátedra 574: taller + práctica clínica, misma comisión.
        html = _pagina(
            comisiones=[
                ["1", "martes", "09:15", "10:45", "Prac", "Tercic", "16", "I", "HY-024", "TALLER"],
                ["", "martes", "11:00", "12:30", "Prac", "Moores", "", "I", "HY-024", "PPIOS"],
            ]
        )
        comisiones = _comisiones(html)

        assert len(comisiones) == 1
        principal = comisiones[0]
        assert principal.codigo == "1"
        assert principal.vacantes == 16
        assert len(principal.partes) == 1

        parte = principal.partes[0]
        assert parte.codigo == "1"  # heredado: es la misma comisión
        assert parte.tipo == "comision"
        assert parte.hora_inicio == time(11, 0)
        assert parte.profesor == "Moores"
        # El cupo es uno solo y vive en la principal.
        assert parte.vacantes is None

    def test_comision_de_cinco_filas_conserva_orden_y_dias(self):
        # Caso de las Prácticas Profesionales: la misma comisión, 5 días.
        dias = ["jueves", "lunes", "martes", "miercoles", "viernes"]
        html = _pagina(
            comisiones=[
                [
                    "4" if i == 0 else "",
                    dia,
                    "13:00",
                    "16:30",
                    "Prac",
                    "Alvarez",
                    "2" if i == 0 else "",
                    "I",
                    "",
                    "",
                ]
                for i, dia in enumerate(dias)
            ]
        )
        comisiones = _comisiones(html)

        assert len(comisiones) == 1
        assert [p.dia for p in comisiones[0].partes] == dias[1:]
        assert all(p.codigo == "4" for p in comisiones[0].partes)

    def test_comision_de_una_fila_no_tiene_partes(self):
        html = _pagina(
            comisiones=[
                ["1", "lunes", "09:00", "11:00", "Prac", "Prof X", "20", "I", "HY-001", "."],
                ["2", "martes", "09:00", "11:00", "Prac", "Prof Y", "20", "I", "HY-001", "."],
            ]
        )
        comisiones = _comisiones(html)

        assert [c.codigo for c in comisiones] == ["1", "2"]
        assert all(c.partes == [] for c in comisiones)

    def test_continuacion_sin_principal_se_descarta(self):
        # Hoy la fuente nunca arranca una tabla sin código, pero si cambiara no
        # hay a qué colgar la fila: descartarla es preferible a explotar.
        html = _pagina(
            comisiones=[
                ["", "lunes", "09:00", "11:00", "Prac", "Huérfana", "", "I", "", ""],
                ["1", "martes", "09:00", "11:00", "Prac", "Prof X", "20", "I", "HY-001", "."],
            ]
        )
        comisiones = _comisiones(html)

        assert len(comisiones) == 1
        assert comisiones[0].codigo == "1"
        assert comisiones[0].partes == []

    def test_teorico_partido_tambien_se_agrupa(self):
        # Hoy la fuente no parte teóricos, pero el modelo no depende del tipo.
        html = _pagina(
            teoricos=[
                ["I", "jueves", "11:00", "12:30", "Teo", "Iuale", "", "", "HY-014", "."],
                ["", "viernes", "11:00", "12:30", "Teo", "Iuale", "", "", "HY-014", "."],
            ]
        )
        detalle = parse_catedra_page(html)
        teoricos = [c for c in detalle.cursos if c.tipo == "teorico"]

        assert len(teoricos) == 1
        assert [p.dia for p in teoricos[0].partes] == ["viernes"]


class TestReplaceCursosConPartes:
    def _detalle(self, cursos) -> CatedraDetalle:
        return CatedraDetalle(
            catedra_id=574,
            cuatrimestre="1",
            numero="1",
            titular="Titular X",
            materia_codigo=10359,
            materia_nombre="Materia X",
            cursos=cursos,
        )

    def _curso(self, codigo="1", vacantes=16, partes=None) -> Curso:
        return Curso(
            tipo="comision",
            codigo=codigo,
            dia="martes",
            hora_inicio=time(9, 15),
            hora_fin=time(10, 45),
            profesor="Tercic",
            vacantes=vacantes,
            obligatorio="I",
            aula="HY-024",
            sede="HY",
            observaciones=None,
            partes=partes or [],
        )

    def _parte(self, codigo="1") -> Curso:
        return Curso(
            tipo="comision",
            codigo=codigo,
            dia="martes",
            hora_inicio=time(11, 0),
            hora_fin=time(12, 30),
            profesor="Moores",
            vacantes=None,
            obligatorio="I",
            aula="HY-024",
            sede="HY",
            observaciones=None,
        )

    def test_las_partes_se_insertan_con_el_id_de_su_principal(self, fake_conn):
        fake_conn.on("delete from cursos", rowcount=2)
        fake_conn.returning_ids = [101, 102]
        detalle = self._detalle(
            [
                self._curso(codigo="1", partes=[self._parte("1")]),
                self._curso(codigo="2", vacantes=15),
            ]
        )

        replace_cursos(fake_conn, detalle)

        inserts = [
            rows
            for sql, rows in fake_conn.executed
            if "insert into cursos" in _normalizar(sql)
        ]
        assert len(inserts) == 2  # principales primero, partes después

        principales, partes = inserts
        assert [r[2] for r in principales] == ["1", "2"]  # codigo
        assert [r[-1] for r in principales] == [None, None]  # parte_de_id

        assert len(partes) == 1
        assert partes[0][2] == "1"  # comparte el código de su principal
        assert partes[0][-1] == 101  # apunta al id que devolvió el RETURNING

    def test_sin_partes_solo_hay_un_insert(self, fake_conn):
        fake_conn.on("delete from cursos", rowcount=1)
        replace_cursos(fake_conn, self._detalle([self._curso()]))

        inserts = [
            rows
            for sql, rows in fake_conn.executed
            if "insert into cursos" in _normalizar(sql)
        ]
        assert len(inserts) == 1


class TestResolveObligatorioIgnoraPartes:
    def test_guardas_en_los_dos_lados_del_join(self, fake_conn):
        # Sin la guarda del lado de la comisión, la parte repetiría el `obligatorio`
        # del padre y el teórico entraría dos veces en la opción: todo plan quedaría
        # solapado contra sí mismo.
        fake_conn.on("insert into comision_obliga", rowcount=0)
        resolve_obligatorio(fake_conn, 574)

        sql = _normalizar(fake_conn.executed[0][0])
        assert "and t.parte_de_id is null" in sql
        assert "and cu.parte_de_id is null" in sql
