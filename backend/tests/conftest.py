"""Fixtures y helpers comunes a toda la suite.

Diseño:
- `FakeConn` imita la interfaz mínima de psycopg que usamos: execute(sql, params)
  devuelve un cursor con fetchall/fetchone/rowcount; commit() es no-op.
- `FakePool` envuelve un FakeConn para que `pool.connection()` (usado en endpoints)
  devuelva el conn dentro de un context manager.
- Firebase: parcheamos `firebase_admin._apps` antes de importar `api.auth` para
  evitar la real `initialize_app()` que requiere GOOGLE_APPLICATION_CREDENTIALS.
"""

from __future__ import annotations

import os
import sys
from datetime import time
from pathlib import Path

# Asegurar que `backend/` esté en sys.path para que `import api.xxx` funcione
# cuando se corre pytest desde otros directorios (ej. desde el hook git).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# --- Env vars que módulos importan a nivel top-level --------------------------
# api.db raisea si DATABASE_URL no está; api.pagos no raisea pero usa varias.
# Seteamos antes de cualquier import de api.*. El pool se crea con open=False
# así que el URL nunca se usa de verdad — en tests mockeamos `pool`.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("MP_ACCESS_TOKEN", "test-mp-token")
os.environ.setdefault("MP_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("APP_URL", "http://localhost:5173")
os.environ.setdefault("APP_URL_BACKEND", "http://localhost:8000")


# --- Firebase bypass (debe correr ANTES de importar api.auth) -----------------
# api/auth.py llama firebase_admin.initialize_app() a nivel de módulo. Si no hay
# credenciales (típico en CI/local), explota. Truco: stuffeamos un app falso en
# `_apps` para que el guard `if not firebase_admin._apps` no entre.
import firebase_admin  # noqa: E402

os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/__fake__")
if not firebase_admin._apps:
    class _FakeApp:
        name = "[DEFAULT]"
        project_id = "test"
        options = type("Opts", (), {"get": lambda self, k, d=None: d})()
        credential = None
        _options = options

    firebase_admin._apps["[DEFAULT]"] = _FakeApp()


# --- FakeConn / FakePool ------------------------------------------------------

import pytest  # noqa: E402


class FakeCursor:
    def __init__(self, rows, rowcount):
        self._rows = list(rows)
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    """Simula una conexión psycopg. Se le registran reglas con `.on(sql_substring, rows=...)`
    y matchea la primera regla cuyo substring (case-insensitive, ignorando whitespace)
    aparezca en el SQL ejecutado. Las reglas se prueban en orden de registro.

    Para SQL idénticos que deben devolver respuestas distintas en llamadas sucesivas,
    pasar `consume=True`: la regla se "gasta" la primera vez.
    """

    def __init__(self):
        self._rules = []  # list of dicts
        self.executed = []  # [(sql, params)]
        self.commits = 0
        self.returning_ids = None  # ids que devuelve executemany(returning=True)

    def on(self, sql_substring, *, rows=None, rowcount=None, consume=False, side_effect=None):
        self._rules.append({
            "match": sql_substring.lower(),
            "rows": rows if rows is not None else [],
            "rowcount": rowcount,
            "consume": consume,
            "consumed": False,
            "side_effect": side_effect,
        })
        return self

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        normalized = " ".join(sql.lower().split())
        for rule in self._rules:
            if rule["consume"] and rule["consumed"]:
                continue
            if rule["match"] in normalized:
                if rule["consume"]:
                    rule["consumed"] = True
                if rule["side_effect"] is not None:
                    rule["side_effect"](sql, params)
                rows = rule["rows"]
                rc = rule["rowcount"] if rule["rowcount"] is not None else len(rows)
                return FakeCursor(rows, rc)
        raise AssertionError(
            f"FakeConn: no hay regla para el SQL:\n{sql[:400]}\nparams={params!r}\n"
            f"Reglas registradas: {[r['match'] for r in self._rules]}"
        )

    def cursor(self):
        return _FakeCursorCtx(self)

    def commit(self):
        self.commits += 1


class _FakeCursorCtx:
    """`with conn.cursor() as cur: cur.executemany(...)` — lo usa replace_cursos.

    Con `returning=True` simula el RETURNING id: un result set por fila insertada,
    recorridos con fetchone()/nextset(). Los ids salen de `conn.returning_ids`
    (default: 1..N) para que el test pueda fijarlos.
    """

    def __init__(self, conn):
        self._conn = conn
        self.executemany_calls = []
        self._returned = []
        self._pos = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def executemany(self, sql, rows, returning=False):
        rows = list(rows)
        self.executemany_calls.append((sql, rows))
        self._conn.executed.append((sql, rows))
        if returning:
            ids = self._conn.returning_ids or list(range(1, len(rows) + 1))
            self._returned = [(i,) for i in ids[: len(rows)]]
            self._pos = 0

    def fetchone(self):
        return self._returned[self._pos] if self._pos < len(self._returned) else None

    def nextset(self):
        self._pos += 1
        return self._pos < len(self._returned)

    def execute(self, sql, params=None):
        return self._conn.execute(sql, params)


class _FakePoolCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *a):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def connection(self):
        return _FakePoolCtx(self.conn)


@pytest.fixture
def fake_conn():
    return FakeConn()


@pytest.fixture
def fake_pool(fake_conn):
    return FakePool(fake_conn)


# --- Helpers para armar filas de DB ------------------------------------------

def make_comision_row(
    *,
    comision_id,
    comision_codigo="01",
    materia_codigo=600,
    materia_nombre="Materia X",
    catedra_id=1,
    catedra_numero="1",
    catedra_titular="Titular X",
    dia="lunes",
    hora_inicio=time(10, 0),
    hora_fin=time(12, 0),
    profesor="Prof X",
    aula="HY101",
    sede="HY",
    vacantes=30,
):
    """Fila como la devuelve _fetch_opciones_por_materia (query principal de comisiones)."""
    return {
        "materia_codigo": materia_codigo,
        "materia_nombre": materia_nombre,
        "catedra_id": catedra_id,
        "catedra_numero": catedra_numero,
        "catedra_titular": catedra_titular,
        "comision_id": comision_id,
        "comision_codigo": comision_codigo,
        "dia": dia,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "profesor": profesor,
        "aula": aula,
        "sede": sede,
        "vacantes": vacantes,
    }


def make_obliga_row(
    *,
    comision_id,
    obliga_id,
    tipo="teorico",
    codigo="T1",
    catedra_id=1,
    dia="martes",
    hora_inicio=time(14, 0),
    hora_fin=time(16, 0),
    aula="HY102",
    profesor=None,
    sede="HY",
    vacantes=None,
):
    """Fila como la devuelve _fetch_opciones_por_materia (query de obligas)."""
    return {
        "comision_id": comision_id,
        "id": obliga_id,
        "tipo": tipo,
        "codigo": codigo,
        "dia": dia,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "aula": aula,
        "profesor": profesor,
        "sede": sede,
        "catedra_id": catedra_id,
        "vacantes": vacantes,
    }


def make_catalogo_row(
    *,
    curso_id,
    tipo="teorico",
    codigo="T1",
    catedra_id=1,
    dia="martes",
    hora_inicio=time(14, 0),
    hora_fin=time(16, 0),
    aula="HY102",
    profesor=None,
    sede="HY",
    vacantes=None,
):
    """Fila como la devuelve _fetch_opciones_por_materia (query del catálogo de
    teóricos y seminarios de la cátedra)."""
    return {
        "id": curso_id,
        "tipo": tipo,
        "codigo": codigo,
        "dia": dia,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "aula": aula,
        "profesor": profesor,
        "sede": sede,
        "catedra_id": catedra_id,
        "vacantes": vacantes,
    }


def make_parte_row(
    *,
    parte_de_id,
    parte_id,
    tipo="comision",
    codigo="01",
    catedra_id=1,
    dia="miercoles",
    hora_inicio=time(10, 0),
    hora_fin=time(12, 0),
    aula="HY103",
    profesor="Prof Y",
    sede="HY",
    vacantes=None,
):
    """Fila como la devuelve _fetch_opciones_por_materia (query de partes).

    `vacantes=None` por default: en la fuente el cupo lo trae sólo la fila principal.
    """
    return {
        "parte_de_id": parte_de_id,
        "id": parte_id,
        "tipo": tipo,
        "codigo": codigo,
        "dia": dia,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "aula": aula,
        "profesor": profesor,
        "sede": sede,
        "catedra_id": catedra_id,
        "vacantes": vacantes,
    }


# Celdas de cada fila: codigo, dia, inicio, fin, tipo, profesor, vac, oblig,
# aula, observ. Una fila con codigo="" es una continuación (parte) de la anterior.
# `headers` se puede pisar para simular un corrimiento de columnas de la fuente.
HEADERS_CATEDRA = (
    "Dia", "Inicio", "Fin", "Tipo", "Profesor", "Vac.", "Oblig.", "Aula", "Observ.",
)


def make_pagina_catedra(
    comisiones=(),
    teoricos=(),
    catedra_id=574,
    materia_codigo=10359,
    cuatrimestre="2025/1",
    headers=HEADERS_CATEDRA,
    con_header=True,
):
    """HTML de una página de detalle de cátedra, como la sirve la fuente.

    `con_header=False` simula una página de error / WAF: 200 sin el `td.option1`
    del que sale el header, que es lo que hace que `parse_catedra_page` devuelva
    None.
    """

    def tabla(titulo, filas):
        if not filas:
            return ""
        ths = "".join(f"<th>{h}</th>" for h in headers)
        cuerpo = "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in fila) + "</tr>" for fila in filas
        )
        return (
            f'<table class="table_tabs"><tr><th>{titulo}</th>{ths}</tr>'
            f"{cuerpo}</table>"
        )

    header = (
        f'<td class="option1">'
        f"{cuatrimestre} * Listado horarios de cátedra {catedra_id} - 1 - Titular X * "
        f"Materia ( {materia_codigo} - Materia X )"
        "</td>"
        if con_header
        else ""
    )
    return (
        "<html><body>"
        + header
        + tabla("Teóricos", teoricos)
        + tabla("Comisiones", comisiones)
        + "</body></html>"
    )


def make_fila_comision(codigo="01", vacantes="30", profesor="Prof X", oblig="I"):
    """Fila de comisión con los 10 campos en el orden de la fuente."""
    return [
        codigo, "lunes", "09:15", "10:45", "Prac", profesor,
        vacantes, oblig, "HY-024", "TALLER",
    ]


def make_fila_db(
    catedra_id=574,
    codigo="01",
    vacantes=30,
    vigente=True,
    cuatrimestre="2025/1",
    congelada=False,
):
    """Fila como la devuelve SELECT_ESTADO de scraper/vacantes.py.

    Tupla, no dict: `scraper/db.get_conn()` no usa dict_row (a diferencia del
    pool del API), así que las filas del scraper vienen posicionales.
    """
    return (catedra_id, codigo, vacantes, vigente, cuatrimestre, congelada)


def setup_planes_db(
    fake_conn,
    comision_rows,
    obliga_rows=None,
    parte_rows=None,
    catalogo_rows=None,
    congeladas=(),
):
    """Registra las queries que ejecuta armar_planes:
    1) FROM materias m JOIN catedras ca JOIN cursos com ...
    2) FROM comision_obliga co JOIN cursos t ...
    3) teóricos y seminarios de las cátedras (catálogo para los flags libres).
    4) FROM cursos p WHERE p.parte_de_id = ANY(...) — encuentros extra.
    5) materias con la oferta congelada (sólo si el request trae solo_con_cupos).

    `catalogo_rows` vacío = la cátedra no dicta teóricos ni seminarios más allá de
    los obligados, que es lo que asumen los tests que no lo pasan.
    """
    fake_conn.on("from materias m", rows=comision_rows)
    fake_conn.on("from comision_obliga co", rows=obliga_rows or [])
    fake_conn.on("t.tipo in ('teorico', 'seminario')", rows=catalogo_rows or [])
    fake_conn.on("where p.parte_de_id", rows=parte_rows or [])
    fake_conn.on(
        "where oferta_congelada", rows=[{"codigo": c} for c in congeladas]
    )
    return fake_conn
