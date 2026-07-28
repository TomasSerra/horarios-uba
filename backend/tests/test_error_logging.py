"""Tests de los handlers globales de error + endpoint /client-errors.

Usamos TestClient SIN context manager para no disparar el lifespan (que abriría
el pool real contra una DB inexistente). `raise_server_exceptions=False` hace que
el catch-all handler forme la respuesta 500 en vez de re-lanzar la excepción.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as main

client = TestClient(main.app, raise_server_exceptions=False)


def test_client_error_endpoint_devuelve_204():
    res = client.post(
        "/client-errors",
        json={"message": "boom", "kind": "onerror", "name": "TypeError"},
    )
    assert res.status_code == 204


def test_client_error_payload_invalido_es_422():
    # Falta `kind` (requerido) → validación 422 con detail estructurado.
    res = client.post("/client-errors", json={"message": "boom"})
    assert res.status_code == 422
    assert "detail" in res.json()


def test_error_de_validador_custom_es_422_serializable():
    # Los validadores custom (model_validator) meten la ValueError original en
    # `ctx`, que json.dumps no serializa: sin el encoder esto devolvía 500.
    res = client.post(
        "/planes", json={"materias": [{"codigo": 4, "comision_codigo": "1"}]}
    )
    assert res.status_code == 422
    assert "comision_codigo requiere catedra_id" in res.text


def test_http_exception_devuelve_detail():
    # Ruta inexistente → 404 formado por el handler de HTTPException.
    res = client.get("/ruta-que-no-existe")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not Found"}


def test_error_no_manejado_es_500_sin_filtrar_internals(monkeypatch):
    # Forzamos un error inesperado dentro de un endpoint: el catch-all devuelve
    # un 500 genérico sin exponer el detalle interno al cliente.
    def _boom():
        raise RuntimeError("secreto interno que no debe filtrarse")

    monkeypatch.setattr(main.pool, "connection", _boom)
    res = client.get("/carreras")
    assert res.status_code == 500
    assert res.json() == {"detail": "Error interno"}
    assert "secreto" not in res.text


# --- CORS en respuestas de error ---------------------------------------------
# Regresión de un incidente real: el 500 salía del ServerErrorMiddleware, que
# está por fuera del CORSMiddleware, así que llegaba sin Access-Control-Allow-
# Origin. El navegador lo bloqueaba y el front veía un TypeError de red en vez
# del 500 → no podía ni mostrar el ErrorState. El orden de los middlewares en
# api/main.py depende de esto: no mover el add_middleware(CORSMiddleware).

ORIGIN = {"Origin": "http://localhost:5173"}


def test_500_lleva_headers_de_cors(monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(main.pool, "connection", _boom)
    res = client.get("/carreras", headers=ORIGIN)
    assert res.status_code == 500
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize(
    "path,status",
    [
        ("/ruta-que-no-existe", 404),  # HTTPException handler
        ("/client-errors", 405),       # method not allowed (GET a un POST)
    ],
)
def test_errores_http_llevan_headers_de_cors(path, status):
    res = client.get(path, headers=ORIGIN)
    assert res.status_code == status
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_422_lleva_headers_de_cors():
    res = client.post("/client-errors", json={"message": "sin kind"}, headers=ORIGIN)
    assert res.status_code == 422
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_preflight_sigue_funcionando():
    res = client.options(
        "/me",
        headers={
            **ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_origen_no_permitido_no_recibe_header():
    res = client.get("/ruta-que-no-existe", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers
