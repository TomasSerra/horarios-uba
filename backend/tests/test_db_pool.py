"""Config del connection pool.

Regresión de un incidente real en prod: en Vercel la instancia se congela entre
invocaciones y Neon corta las conexiones ociosas. Sin `check`, el pool entregaba
una conexión muerta y la primera query tras el descongelamiento moría con
"SSL connection has been closed unexpectedly" (500 esporádicos en /me, /catedras
y cualquier otro endpoint).
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool

from api.db import pool


def test_pool_valida_conexiones_en_el_checkout():
    assert pool._check is ConnectionPool.check_connection


def test_pool_no_se_abre_al_importar():
    # El pool se abre en el lifespan, no al import: en tests nunca toca la DB.
    assert pool.closed
