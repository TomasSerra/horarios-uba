from __future__ import annotations

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está configurada")

pool = ConnectionPool(
    DATABASE_URL,
    kwargs={"row_factory": dict_row},
    min_size=1,
    max_size=5,
    # Con max_size=5 (Neon Free), un burst chico encola requests. Timeout
    # explícito para que el cliente reciba 500 rápido en vez de colgar
    # 30s (default de psycopg-pool). Métricas en Render lo hacen visible.
    timeout=5.0,
    # En Vercel la instancia se congela entre invocaciones y Neon corta las
    # conexiones ociosas; los workers de mantenimiento del pool también quedan
    # congelados, así que nadie se entera. Sin `check`, la primera query tras el
    # descongelamiento agarra una conexión muerta y revienta con
    # "SSL connection has been closed unexpectedly". Con `check` el pool valida
    # en el checkout (un round-trip vacío) y reemplaza la conexión muerta.
    check=ConnectionPool.check_connection,
    open=False,
)
