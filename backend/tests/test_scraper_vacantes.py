"""Tests del job horario que actualiza sólo `cursos.vacantes`.

Lo que se protege acá es el invariante: se escribe **sólo** sobre la intersección
(fuente ∩ DB) y **sólo** valores int efectivamente vistos. Nunca NULL, nunca 0
por ausencia, nunca un DELETE o un INSERT.

Sin red (el fetcher se inyecta) y sin DB (FakeConn). El HTML se construye con
`make_pagina_catedra` de conftest.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from .conftest import make_fila_comision, make_fila_db, make_pagina_catedra

from scraper.discover import IndexEntry
from scraper.vacantes import (
    SELECT_ESTADO,
    _Abortar,
    actualizar,
    calcular_payload,
    recolectar,
    validar_headers_comisiones,
)
from scraper.vacantes_guardas import MAX_FALLOS_CONSECUTIVOS, MetricasVacantes


def _entry(catedra_id):
    return IndexEntry(
        catedra_id=catedra_id,
        materia_nombre="Materia X",
        titular_raw="Titular X",
        carrera_slug="licenciatura-psicologia",
    )


def _fetcher(paginas_por_catedra):
    """Fake de `fetch`: devuelve el HTML registrado para esa cátedra."""

    def fetch_fn(_url, params=None):
        catedra_id = params["catedra"]
        if catedra_id not in paginas_por_catedra:
            raise RuntimeError(f"404 catedra={catedra_id}")
        return paginas_por_catedra[catedra_id]

    return fetch_fn


def _recolectar(paginas_por_catedra, ids=None):
    m = MetricasVacantes()
    entries = [_entry(i) for i in (ids or sorted(paginas_por_catedra))]
    paginas = recolectar(
        entries, m, fetch_fn=_fetcher(paginas_por_catedra), delay=0
    )
    return paginas, m


def _normalizar(sql: str) -> str:
    return " ".join(sql.lower().split())


# --- Validación de shape ------------------------------------------------------


class TestValidarHeaders:
    def test_headers_de_siempre_pasan(self):
        html = make_pagina_catedra(comisiones=[make_fila_comision()])
        assert validar_headers_comisiones(html) == "ok"

    def test_columna_insertada_antes_de_vac_se_rechaza(self):
        # El detector primario del corrimiento: `parse._parse_rows` lee cells[6]
        # posicionalmente y seguiría devolviendo números plausibles de otra celda.
        html = make_pagina_catedra(
            comisiones=[make_fila_comision()],
            headers=(
                "Dia", "Inicio", "Fin", "Tipo", "Cupo", "Profesor",
                "Vac.", "Oblig.", "Aula", "Observ.",
            ),
        )
        assert validar_headers_comisiones(html) == "shape_mala"

    def test_sin_tabla_de_comisiones(self):
        html = make_pagina_catedra(teoricos=[make_fila_comision(codigo="T1")])
        assert validar_headers_comisiones(html) == "sin_tabla"

    def test_tabla_con_menos_columnas_se_rechaza(self):
        html = make_pagina_catedra(
            comisiones=[make_fila_comision()], headers=("Dia", "Inicio")
        )
        assert validar_headers_comisiones(html) == "shape_mala"

    def test_vac_con_nbsp_y_mayusculas_igual_pasa(self):
        html = make_pagina_catedra(
            comisiones=[make_fila_comision()],
            headers=(
                "Dia", "Inicio", "Fin", "Tipo", "Profesor", "VAC\xa0",
                "Oblig.", "Aula", "Observ.",
            ),
        )
        assert validar_headers_comisiones(html) == "ok"


# --- Recolección --------------------------------------------------------------


class TestRecolectar:
    def test_caso_feliz(self):
        html = make_pagina_catedra(
            comisiones=[
                make_fila_comision(codigo="01", vacantes="30"),
                make_fila_comision(codigo="02", vacantes="0"),
            ]
        )
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": 30, "02": 0}
        assert paginas[574].cuatrimestre == "2025/1"
        assert (m.paginas_ok, m.claves_fuente, m.con_valor) == (1, 2, 2)

    def test_cero_es_un_valor_valido_no_un_none(self):
        # La fuente publica 0 cuando la comisión se llena: es el dato que más
        # importa durante inscripciones y tiene que escribirse.
        html = make_pagina_catedra(comisiones=[make_fila_comision(vacantes="0")])
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": 0}
        assert m.sin_valor == 0

    def test_celda_vacia_es_none_y_no_se_escribe(self):
        html = make_pagina_catedra(comisiones=[make_fila_comision(vacantes="")])
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": None}
        assert (m.sin_valor, m.con_valor) == (1, 0)

    def test_las_partes_no_aportan_claves(self):
        # Fila con código vacío = otro encuentro de la comisión anterior. No trae
        # cupo propio y comparte el código del padre.
        html = make_pagina_catedra(
            comisiones=[
                make_fila_comision(codigo="01", vacantes="16"),
                make_fila_comision(codigo="", vacantes=""),
            ]
        )
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": 16}
        assert m.claves_fuente == 1

    def test_solo_comisiones_no_teoricos(self):
        html = make_pagina_catedra(
            comisiones=[make_fila_comision(codigo="01", vacantes="30")],
            teoricos=[make_fila_comision(codigo="T1", vacantes="99")],
        )
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": 30}
        assert m.claves_fuente == 1

    def test_codigo_duplicado_descarta_ambos(self):
        html = make_pagina_catedra(
            comisiones=[
                make_fila_comision(codigo="01", vacantes="30"),
                make_fila_comision(codigo="01", vacantes="12"),
            ]
        )
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {}
        assert m.duplicadas_en_pagina == 1

    @pytest.mark.parametrize("valor", ["2025", "-1000", "5000"])
    def test_fuera_de_rango_se_descarta(self, valor):
        # "2025" es el caso que importa: un año leído desde otra columna.
        html = make_pagina_catedra(
            comisiones=[make_fila_comision(vacantes=valor)]
        )
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": None}
        assert (m.fuera_de_rango, m.con_valor) == (1, 0)

    @pytest.mark.parametrize("valor", ["850", "800", "1200"])
    def test_comisiones_virtuales_grandes_son_validas(self, valor):
        # Las asincrónicas por campus virtual tienen cupos de tres cifras largas:
        # Idioma Inglés Módulo II (cátedra 854) tiene 850. Un techo apretado las
        # descartaría en silencio.
        html = make_pagina_catedra(comisiones=[make_fila_comision(vacantes=valor)])
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": int(valor)}
        assert (m.con_valor, m.fuera_de_rango) == (1, 0)

    def test_negativo_chico_es_valido(self):
        # Sobrecupo: existe en la fuente y el resto del sistema lo trata como
        # "sin cupo" (`solo_con_cupos` pide > 0).
        html = make_pagina_catedra(comisiones=[make_fila_comision(vacantes="-3")])
        paginas, m = _recolectar({574: html})
        assert paginas[574].vacantes == {"01": -3}
        assert m.con_valor == 1

    def test_html_de_error_cuenta_como_sin_parse(self):
        html = make_pagina_catedra(
            comisiones=[make_fila_comision()], con_header=False
        )
        paginas, m = _recolectar({574: html})
        assert paginas == {}
        assert (m.paginas_sin_parse, m.paginas_ok) == (1, 0)

    def test_catedra_distinta_a_la_pedida_se_descarta(self):
        # Redirect o sesión cruzada: la página dice otra cátedra.
        html = make_pagina_catedra(
            comisiones=[make_fila_comision()], catedra_id=999
        )
        paginas, m = _recolectar({574: html}, ids=[574])
        assert paginas == {}
        assert m.paginas_catedra_mismatch == 1

    def test_shape_mala_se_descarta_sin_recolectar_nada(self):
        html = make_pagina_catedra(
            comisiones=[make_fila_comision()],
            headers=(
                "Dia", "Inicio", "Fin", "Tipo", "Cupo", "Profesor",
                "Vac.", "Oblig.", "Aula", "Observ.",
            ),
        )
        paginas, m = _recolectar({574: html})
        assert paginas == {}
        assert (m.paginas_shape_mala, m.claves_fuente) == (1, 0)

    def test_fallo_http_aislado_no_corta(self):
        paginas_html = {
            cid: make_pagina_catedra(
                comisiones=[make_fila_comision()], catedra_id=cid
            )
            for cid in (574, 999)
        }
        paginas, m = _recolectar(paginas_html, ids=[574, 111, 999])
        assert set(paginas) == {574, 999}
        assert (m.paginas_http_error, m.corte_por_fallos) == (1, False)

    def test_corta_a_los_n_fallos_consecutivos(self):
        # Cortesía con la fuente: no moler 219 páginas contra un WAF.
        ids = list(range(1, 20))
        m = MetricasVacantes()
        recolectar([_entry(i) for i in ids], m, fetch_fn=_fetcher({}), delay=0)
        assert m.corte_por_fallos
        assert m.paginas_http_error == MAX_FALLOS_CONSECUTIVOS


# --- Diff ---------------------------------------------------------------------


def _paginas(catedra_id=574, vacantes=None, cuatrimestre="2025/1"):
    from scraper.vacantes import PaginaVacantes

    return {
        catedra_id: PaginaVacantes(
            catedra_id=catedra_id,
            cuatrimestre=cuatrimestre,
            vacantes=vacantes if vacantes is not None else {"01": 12},
        )
    }


class TestCalcularPayload:
    def test_valor_distinto_entra(self):
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 12}), [make_fila_db(vacantes=30)], m
        )
        assert payload == [(574, "01", 12)]
        assert (m.cambios, m.matched) == (1, 1)

    def test_valor_igual_no_entra(self):
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 30}), [make_fila_db(vacantes=30)], m
        )
        assert payload == []
        assert (m.cambios, m.matched) == (0, 1)

    def test_db_null_y_fuente_int_entra(self):
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 5}), [make_fila_db(vacantes=None)], m
        )
        assert payload == [(574, "01", 5)]

    def test_fuente_none_no_entra_y_se_cuenta(self):
        # La regla conservadora: una celda vacía nunca borra el valor que hay.
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": None}), [make_fila_db(vacantes=30)], m
        )
        assert payload == []
        assert m.nuevos_null_en_db == 1

    def test_cero_de_la_fuente_se_escribe(self):
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 0}), [make_fila_db(vacantes=30)], m
        )
        assert payload == [(574, "01", 0)]

    def test_mismatch_de_cuatrimestre_saltea_la_catedra_entera(self):
        # La misma clave apunta a otra comisión: escribir sería pisar la oferta
        # vieja con cupos de la nueva.
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 1, "02": 2}, cuatrimestre="2025/2"),
            [
                make_fila_db(codigo="01", vacantes=30, cuatrimestre="2025/1"),
                make_fila_db(codigo="02", vacantes=30, cuatrimestre="2025/1"),
            ],
            m,
        )
        assert payload == []
        assert m.saltadas_por_cuatrimestre == 1
        assert m.claves_db == 0

    def test_no_vigente_se_descarta(self):
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 12}), [make_fila_db(vigente=False)], m
        )
        assert payload == []
        assert m.descartadas_no_vigente == 1
        assert m.claves_db == 0

    def test_claves_db_se_acota_a_las_catedras_leidas(self):
        # Una cátedra cuya página falló no arrastra las métricas de cobertura:
        # ya la contó el breaker de paginas_ok. Es lo que hace que --limit
        # funcione sin caso especial.
        m = MetricasVacantes()
        calcular_payload(
            _paginas(catedra_id=574, vacantes={"01": 12}),
            [
                make_fila_db(catedra_id=574, codigo="01", vacantes=30),
                make_fila_db(catedra_id=999, codigo="01", vacantes=30),
            ],
            m,
        )
        assert m.claves_db == 1
        assert m.matched == 1
        assert m.sin_ver_db == 0

    def test_comision_de_la_fuente_que_no_esta_en_la_db(self):
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 12, "99": 5}),
            [make_fila_db(codigo="01", vacantes=30)],
            m,
        )
        assert payload == [(574, "01", 12)]
        assert m.sin_match_fuente == 1

    def test_comision_de_la_db_que_no_esta_en_la_fuente(self):
        # Comisión cancelada: se deja stale, nunca se pone NULL ni 0.
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 12}),
            [
                make_fila_db(codigo="01", vacantes=30),
                make_fila_db(codigo="02", vacantes=30),
            ],
            m,
        )
        assert payload == [(574, "01", 12)]
        assert m.sin_ver_db == 1

    def test_materia_congelada_se_cuenta_pero_no_se_excluye(self):
        # Excluirlas dejaría Psicopatología y Freud stale toda la semana; el
        # match de cuatrimestre ya cubre el caso peligroso.
        m = MetricasVacantes()
        payload = calcular_payload(
            _paginas(vacantes={"01": 12}),
            [make_fila_db(vacantes=30, congelada=True)],
            m,
        )
        assert payload == [(574, "01", 12)]
        assert m.en_materia_congelada == 1


# --- Escritura ----------------------------------------------------------------


def _patch_conn(monkeypatch, fake_conn):
    @contextmanager
    def fake_get_conn():
        yield fake_conn

    monkeypatch.setattr("scraper.vacantes.get_conn", fake_get_conn)


def _con_reglas_base(fake_conn, filas_db):
    fake_conn.on("set local", rows=[])
    fake_conn.on("from cursos c", rows=filas_db)
    return fake_conn


class TestActualizar:
    def test_update_lleva_todas_las_guardas(self, fake_conn, monkeypatch):
        _patch_conn(monkeypatch, fake_conn)
        _con_reglas_base(fake_conn, [make_fila_db(vacantes=30)])
        fake_conn.on("update cursos", rowcount=1)

        actualizar(
            _paginas(vacantes={"01": 12}),
            MetricasVacantes(),
            dry_run=False,
            forzar=False,
        )

        sql = _normalizar(
            next(s for s, _ in fake_conn.executed if "update cursos" in s.lower())
        )
        # Sin parte_de_id el cupo del padre se copiaría a sus partes.
        assert "c.parte_de_id is null" in sql
        assert "c.tipo = 'comision'" in sql
        # unnest rellena con NULL si los arrays tienen largo distinto.
        assert "v.vacantes is not null" in sql
        # Deja el rowcount exactamente asertable y no genera WAL de más.
        assert "c.vacantes is distinct from v.vacantes" in sql

    def test_params_son_tres_arrays_del_mismo_largo_sin_none(
        self, fake_conn, monkeypatch
    ):
        _patch_conn(monkeypatch, fake_conn)
        _con_reglas_base(
            fake_conn,
            [
                make_fila_db(codigo="01", vacantes=30),
                make_fila_db(codigo="02", vacantes=30),
            ],
        )
        fake_conn.on("update cursos", rowcount=2)

        actualizar(
            _paginas(vacantes={"01": 12, "02": 0}),
            MetricasVacantes(),
            dry_run=False,
            forzar=False,
        )

        _, params = next(
            (s, p) for s, p in fake_conn.executed if "update cursos" in s.lower()
        )
        assert len(params["catedras"]) == len(params["codigos"]) == len(
            params["vacantes"]
        ) == 2
        assert None not in params["vacantes"]
        assert set(params["codigos"]) == {"01", "02"}

    def test_payload_vacio_no_ejecuta_update(self, fake_conn, monkeypatch):
        # No se registra regla para el UPDATE: si se ejecutara, FakeConn raisea.
        _patch_conn(monkeypatch, fake_conn)
        _con_reglas_base(fake_conn, [make_fila_db(vacantes=30)])

        actualizar(
            _paginas(vacantes={"01": 30}),
            MetricasVacantes(),
            dry_run=False,
            forzar=False,
        )

        assert not any("update" in s.lower() for s, _ in fake_conn.executed)

    def test_dry_run_no_ejecuta_update_y_pone_read_only(
        self, fake_conn, monkeypatch
    ):
        _patch_conn(monkeypatch, fake_conn)
        _con_reglas_base(fake_conn, [make_fila_db(vacantes=30)])

        actualizar(
            _paginas(vacantes={"01": 12}),
            MetricasVacantes(),
            dry_run=True,
            forzar=False,
        )

        assert not any("update" in s.lower() for s, _ in fake_conn.executed)
        assert fake_conn.read_only is True

    def test_decision_de_no_escribir_aborta_sin_update(self, fake_conn, monkeypatch):
        # Cambia el 100% de 100 comisiones: el breaker de cambios masivos corta.
        # Es la firma de un parse que leyó otra columna y dio ints plausibles.
        _patch_conn(monkeypatch, fake_conn)
        filas = [make_fila_db(codigo=f"{i:03d}", vacantes=30) for i in range(100)]
        _con_reglas_base(fake_conn, filas)

        m = MetricasVacantes(claves_fuente=100, con_valor=100)
        with pytest.raises(_Abortar, match="otra columna"):
            actualizar(
                _paginas(vacantes={f"{i:03d}": 1 for i in range(100)}),
                m,
                dry_run=False,
                forzar=False,
            )

        assert not any("update" in s.lower() for s, _ in fake_conn.executed)

    def test_muestra_chica_no_dispara_el_breaker_de_ratio(
        self, fake_conn, monkeypatch
    ):
        # Con 1 comisión matcheada, un cambio es el 100%: sin el piso de muestra
        # una corrida con --limit abortaría siempre.
        _patch_conn(monkeypatch, fake_conn)
        _con_reglas_base(fake_conn, [make_fila_db(vacantes=30)])
        fake_conn.on("update cursos", rowcount=1)

        actualizar(
            _paginas(vacantes={"01": 12}),
            MetricasVacantes(),
            dry_run=False,
            forzar=False,
        )

        assert any("update cursos" in s.lower() for s, _ in fake_conn.executed)

    def test_rowcount_de_mas_raisea(self, fake_conn, monkeypatch):
        _patch_conn(monkeypatch, fake_conn)
        _con_reglas_base(fake_conn, [make_fila_db(vacantes=30)])
        fake_conn.on("update cursos", rowcount=5)

        with pytest.raises(RuntimeError, match="única"):
            actualizar(
                _paginas(vacantes={"01": 12}),
                MetricasVacantes(),
                dry_run=False,
                forzar=False,
            )


def test_el_select_solo_mira_comisiones_principales():
    sql = _normalizar(SELECT_ESTADO)
    assert "c.tipo = 'comision'" in sql
    assert "c.parte_de_id is null" in sql
    # vigente y cuatrimestre viajan para filtrar en Python y poder contar por qué
    # se descarta cada clave.
    assert "ca.vigente" in sql
    assert "ca.cuatrimestre" in sql
