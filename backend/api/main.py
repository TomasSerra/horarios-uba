from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# En Vercel (serverless) no hay proceso Uvicorn que configure el root logger, así
# que lo hacemos nosotros: sin esto los `log.info` no se emiten y no hay formato
# uniforme. `force=True` gana sobre cualquier handler que Uvicorn ya haya puesto
# en dev local.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)
log = logging.getLogger("main")

from .auth import AuthUser, optional_user
from .db import pool
from .models import (
    Carrera,
    CatedraDetail,
    CatedraOpcion,
    CatedraSummary,
    ClientErrorReport,
    ComisionOpcion,
    CursoListItem,
    CursoResponse,
    CursoSummary,
    HealthResponse,
    MateriaDetail,
    MateriaListItem,
    MateriaOpciones,
    ProfesorRating,
)
from .favoritos import router as favoritos_router
from .me import router as me_router
from .pagos import router as pagos_router
from .planes import PlanRequest, PlanResponse, armar_planes
from .reviews import router as reviews_router
from .subs import has_active_subscription


def _fetch_obliga_map(conn, comision_ids: list[int]) -> dict[int, list[CursoSummary]]:
    """Devuelve {comision_id: [CursoSummary, ...]} para el set de comisiones dado."""
    if not comision_ids:
        return {}
    rows = conn.execute(
        """
        SELECT co.comision_id,
               t.id, t.tipo::text AS tipo, t.codigo, t.dia,
               t.hora_inicio, t.hora_fin, t.aula
          FROM comision_obliga co
          JOIN cursos t ON t.id = co.obliga_a_id
         WHERE co.comision_id = ANY(%s)
         ORDER BY t.tipo, t.codigo
        """,
        (comision_ids,),
    ).fetchall()
    out: dict[int, list[CursoSummary]] = defaultdict(list)
    for row in rows:
        comision_id = row.pop("comision_id")
        out[comision_id].append(CursoSummary(**row))
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    pool.wait()
    if os.environ.get("MP_SKIP_SIGNATURE") == "1":
        log.warning(
            "MP_SKIP_SIGNATURE=1 — verificación de firma del webhook DESACTIVADA. "
            "Solo aceptable en dev. Sacar en prod."
        )
    yield
    pool.close()


app = FastAPI(
    title="Horarios — Facultad de Psicología (UBA)",
    description="API para consultar horarios de cátedras.",
    version="0.1.0",
    lifespan=lifespan,
)

_allowed_origins = ["http://localhost:5173", "http://localhost:3000"]
if (_app_url := os.environ.get("APP_URL")) and _app_url not in _allowed_origins:
    _allowed_origins.append(_app_url.rstrip("/"))

app.add_middleware(GZipMiddleware, minimum_size=500)
# OJO: el CORSMiddleware se agrega MÁS ABAJO, después de `log_unhandled`, para
# que quede por fuera de él. Ver el comentario ahí.

app.include_router(me_router)
app.include_router(pagos_router, prefix="/pagos")
app.include_router(favoritos_router, prefix="/favoritos")
# GET /catedras (ranking) y {GET,PUT,DELETE} /catedras/{id}/reviews. No colisiona
# con el GET /catedras/{catedra_id} definido más abajo (rutas distintas).
app.include_router(reviews_router, prefix="/catedras")


def _req_id(request: Request) -> str:
    # Vercel inyecta un id por invocación; sirve para correlacionar en los logs.
    return request.headers.get("x-vercel-id", "-")


def _error_500() -> JSONResponse:
    # Sin detalle interno: el stack ya quedó en los logs.
    return JSONResponse(status_code=500, content={"detail": "Error interno"})


@app.middleware("http")
async def log_unhandled(request: Request, call_next):
    # Única fuente del log de excepciones NO manejadas: las ve acá con stack,
    # contexto y latencia. Los HTTPException/422 ya se convirtieron en Response
    # más adentro (los loguean sus handlers), así que acá solo caen los errores
    # inesperados (incluidos los de DB/pool que antes se perdían).
    start = time.perf_counter()
    try:
        return await call_next(request)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.error(
            "Unhandled %s en %s %s?%s (req=%s, %.0fms): %s",
            exc.__class__.__name__,
            request.method,
            request.url.path,
            request.url.query,
            _req_id(request),
            elapsed_ms,
            exc,
            exc_info=True,
        )
        # Devolvemos la respuesta acá en vez de re-lanzar: si la excepción sube,
        # el 500 lo arma el ServerErrorMiddleware de Starlette, que está por
        # FUERA del CORSMiddleware → sale sin Access-Control-Allow-Origin y el
        # navegador la bloquea (el front ve un TypeError de red en vez de un 500
        # y no puede ni mostrar el error). Cortando acá, la respuesta pasa por
        # CORS y llega legible.
        return _error_500()


# Se agrega DESPUÉS de `log_unhandled` a propósito: Starlette apila cada
# middleware por fuera del anterior, así que el último agregado es el más
# externo. CORS tiene que envolver a `log_unhandled` para que TODA respuesta
# —incluidos los 500— salga con los headers de CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
    log.log(
        level,
        "HTTP %s en %s %s (req=%s): %s",
        exc.status_code,
        request.method,
        request.url.path,
        _req_id(request),
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log.warning(
        "HTTP 422 en %s %s (req=%s): %s",
        request.method,
        request.url.path,
        _req_id(request),
        exc.errors(),
    )
    # Los errores de un validador custom traen la ValueError original en `ctx`,
    # que `json.dumps` no serializa: sin el encoder el 422 se vuelve un 500.
    return JSONResponse(
        status_code=422, content={"detail": jsonable_encoder(exc.errors())}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Red de seguridad: hoy `log_unhandled` corta todo antes y devuelve el 500,
    # así que acá solo caería algo que explote en el propio CORSMiddleware. Esa
    # respuesta no lleva headers de CORS (sale del ServerErrorMiddleware), pero
    # es preferible a un 502 del runtime.
    return _error_500()


@app.post("/client-errors", status_code=204)
async def report_client_error(report: ClientErrorReport, request: Request):
    """Recibe errores del navegador (SPA sin funciones propias en Vercel) y los
    loguea con prefijo [client-error] para que aparezcan en los Runtime Logs de
    este proyecto. Nunca falla: cualquier problema se traga y responde 204."""
    try:
        log.error(
            "[client-error] kind=%s name=%s url=%s ua=%s req=%s msg=%s%s%s",
            report.kind,
            report.name,
            report.url,
            report.user_agent,
            _req_id(request),
            report.message,
            f"\n{report.stack}" if report.stack else "",
            f"\ncomponentStack:{report.component_stack}" if report.component_stack else "",
        )
    except Exception:
        pass
    return Response(status_code=204)


# Datos servidos por el scraper diario (06:00 UTC), estables durante el día.
# Fresco 20 min y hasta 40 min más sirviendo stale mientras revalida en
# background: ventana total de 1 hora. Antes era 1h + 24h, pero ese colchón
# largo hace que un cambio de shape del payload (agregar un campo que el FE
# necesita) quede invisible por un día entero después del deploy.
_STATIC_CACHE = "public, max-age=1200, stale-while-revalidate=2400"


def _set_static_cache(response: Response) -> None:
    response.headers["Cache-Control"] = _STATIC_CACHE
    # Cache `public` + CORS dinámico por Origin: sin Vary: Origin, un proxy
    # compartido podría servir respuestas con el ACAO equivocado a otro
    # origen. GZipMiddleware ya appendea Accept-Encoding después.
    response.headers["Vary"] = "Origin"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    db_status = "ok"
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        db_status = f"error: {exc!r}"
    return HealthResponse(status="ok", db=db_status)


@app.get("/carreras", response_model=list[Carrera])
def list_carreras(response: Response) -> list[Carrera]:
    _set_static_cache(response)
    # `sedes` se computa desde `cursos.sede` para que el FE filtre el panel
    # de sedes y el dropdown por materia a sólo las que existen en la carrera.
    # Sólo cátedras vigentes: una sede que este cuatrimestre no se usa no debe
    # ofrecerse como filtro.
    sql = """
        SELECT
            c.slug,
            c.nombre,
            COALESCE(
                array_agg(DISTINCT cu.sede ORDER BY cu.sede)
                  FILTER (WHERE cu.sede IS NOT NULL AND cu.sede <> ''),
                ARRAY[]::text[]
            ) AS sedes
        FROM carreras c
        LEFT JOIN materias m  ON m.carrera = c.slug
        LEFT JOIN catedras ca ON ca.materia_codigo = m.codigo AND ca.vigente
        LEFT JOIN cursos cu   ON cu.catedra_id = ca.id
        GROUP BY c.slug, c.nombre, c.sort_order
        ORDER BY c.sort_order, c.nombre
    """
    with pool.connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [Carrera(**row) for row in rows]


@app.get("/materias", response_model=list[MateriaListItem])
def list_materias(
    response: Response,
    q: str | None = Query(None, description="Filtrar por nombre (case-insensitive)"),
    carrera: str | None = Query(None, description="Slug de carrera"),
) -> list[MateriaListItem]:
    _set_static_cache(response)
    # Se devuelven todas las materias, incluidas las que ya no se dictan: el
    # buscador de reseñas las necesita. `cant_catedras_vigentes` es lo que mira
    # el selector del armador de planes para ocultar las que están en 0.
    sql = """
        SELECT m.codigo, m.nombre, m.anual,
               COUNT(c.id) AS cant_catedras,
               COUNT(c.id) FILTER (WHERE c.vigente) AS cant_catedras_vigentes
          FROM materias m
          LEFT JOIN catedras c ON c.materia_codigo = m.codigo
         WHERE (%(pattern)s::text IS NULL OR m.nombre ILIKE %(pattern)s)
           AND (%(carrera)s::text IS NULL OR m.carrera = %(carrera)s)
         GROUP BY m.codigo, m.nombre, m.anual
         ORDER BY m.nombre
    """
    pattern = f"%{q}%" if q else None
    with pool.connection() as conn:
        rows = conn.execute(
            sql,
            {"pattern": pattern, "carrera": carrera},
        ).fetchall()
    return [MateriaListItem(**row) for row in rows]


@app.get("/materias/{codigo}", response_model=MateriaDetail)
def get_materia(codigo: int, response: Response) -> MateriaDetail:
    _set_static_cache(response)
    with pool.connection() as conn:
        materia = conn.execute(
            "SELECT codigo, nombre FROM materias WHERE codigo = %s",
            (codigo,),
        ).fetchone()
        if materia is None:
            raise HTTPException(status_code=404, detail="Materia no encontrada")
        catedras = conn.execute(
            """
            SELECT id, numero, titular, cuatrimestre, vigente
              FROM catedras
             WHERE materia_codigo = %s
             ORDER BY id
            """,
            (codigo,),
        ).fetchall()
    return MateriaDetail(
        codigo=materia["codigo"],
        nombre=materia["nombre"],
        catedras=[CatedraSummary(**row) for row in catedras],
    )


@app.get("/materias/{codigo}/opciones", response_model=MateriaOpciones)
def get_materia_opciones(codigo: int, response: Response) -> MateriaOpciones:
    """Devuelve la materia con sus cátedras y, para cada una, los profesores
    únicos que dictan comisiones (datos necesarios para que el FE permita
    elegir cátedra y filtrar por profesores antes de armar planes).

    Incluye cátedras no vigentes (con `vigente=False`): este endpoint también lo
    consume el diálogo de reseñas, que debe poder reseñar cátedras que ya no se
    dictan. El armador de planes filtra por `vigente` del lado del FE."""
    _set_static_cache(response)
    with pool.connection() as conn:
        materia = conn.execute(
            "SELECT codigo, nombre FROM materias WHERE codigo = %s",
            (codigo,),
        ).fetchone()
        if materia is None:
            raise HTTPException(status_code=404, detail="Materia no encontrada")
        # avg_rating/review_count van como subqueries correlacionadas (no como
        # LEFT JOIN a catedra_reviews) para no multiplicar las filas de comisiones
        # y romper los array_agg/jsonb_agg de profesores y comisiones.
        rows = conn.execute(
            """
            SELECT ca.id, ca.numero, ca.titular, ca.cuatrimestre, ca.vigente,
                   COALESCE(
                       array_agg(DISTINCT cu.profesor)
                         FILTER (WHERE cu.profesor IS NOT NULL),
                       ARRAY[]::text[]
                   ) AS profesores,
                   COALESCE(
                       jsonb_agg(DISTINCT jsonb_build_object(
                           'codigo', cu.codigo,
                           'profesor', cu.profesor, 'sede', cu.sede))
                         FILTER (WHERE cu.id IS NOT NULL),
                       '[]'::jsonb
                   ) AS comisiones,
                   (SELECT AVG(r.rating)::float FROM catedra_reviews r
                     WHERE r.catedra_id = ca.id) AS avg_rating,
                   (SELECT COUNT(*) FROM catedra_reviews r
                     WHERE r.catedra_id = ca.id) AS review_count,
                   -- Si alguna comisión de la cátedra obliga un curso de ese
                   -- tipo. El FE muestra el toggle de "coincide con su práctico"
                   -- sólo si hay algo atado que desatar.
                   EXISTS (SELECT 1
                             FROM cursos com
                             JOIN comision_obliga co ON co.comision_id = com.id
                             JOIN cursos t ON t.id = co.obliga_a_id
                            WHERE com.catedra_id = ca.id
                              AND t.tipo = 'teorico') AS obliga_teorico,
                   EXISTS (SELECT 1
                             FROM cursos com
                             JOIN comision_obliga co ON co.comision_id = com.id
                             JOIN cursos t ON t.id = co.obliga_a_id
                            WHERE com.catedra_id = ca.id
                              AND t.tipo = 'seminario') AS obliga_seminario
              FROM catedras ca
              LEFT JOIN cursos cu ON cu.catedra_id = ca.id AND cu.tipo = 'comision'
             WHERE ca.materia_codigo = %s
             GROUP BY ca.id, ca.numero, ca.titular, ca.cuatrimestre, ca.vigente
             ORDER BY ca.id
            """,
            (codigo,),
        ).fetchall()
        # Promedio por profesor (por nombre) agregando su nota dedicada
        # (profesor_rating) de las reseñas de todas las cátedras de la materia.
        prof_rating_rows = conn.execute(
            """
            SELECT r.profesor,
                   AVG(r.profesor_rating)::float AS avg_rating,
                   COUNT(*) AS review_count
              FROM catedra_reviews r
              JOIN catedras ca ON ca.id = r.catedra_id
             WHERE ca.materia_codigo = %s
               AND r.profesor IS NOT NULL
               AND r.profesor_rating IS NOT NULL
             GROUP BY r.profesor
            """,
            (codigo,),
        ).fetchall()
    return MateriaOpciones(
        codigo=materia["codigo"],
        nombre=materia["nombre"],
        profesores_rating={
            r["profesor"]: ProfesorRating(
                avg_rating=round(r["avg_rating"], 2),
                review_count=r["review_count"],
            )
            for r in prof_rating_rows
        },
        catedras=[
            CatedraOpcion(
                id=r["id"],
                numero=r["numero"],
                titular=r["titular"],
                cuatrimestre=r["cuatrimestre"],
                vigente=r["vigente"],
                profesores=sorted(r["profesores"]),
                comisiones=[ComisionOpcion(**c) for c in r["comisiones"]],
                obliga_teorico=r["obliga_teorico"],
                obliga_seminario=r["obliga_seminario"],
                avg_rating=(
                    round(r["avg_rating"], 2) if r["avg_rating"] is not None else None
                ),
                review_count=r["review_count"],
            )
            for r in rows
        ],
    )


@app.get("/catedras/{catedra_id}", response_model=CatedraDetail)
def get_catedra(catedra_id: int, response: Response) -> CatedraDetail:
    _set_static_cache(response)
    with pool.connection() as conn:
        catedra = conn.execute(
            """
            SELECT c.id, c.materia_codigo, m.nombre AS materia_nombre,
                   c.numero, c.titular, c.cuatrimestre, c.vigente
              FROM catedras c
              JOIN materias m ON m.codigo = c.materia_codigo
             WHERE c.id = %s
            """,
            (catedra_id,),
        ).fetchone()
        if catedra is None:
            raise HTTPException(status_code=404, detail="Cátedra no encontrada")
        cursos = conn.execute(
            """
            SELECT id, catedra_id, tipo::text, codigo, dia,
                   hora_inicio, hora_fin, profesor, vacantes,
                   obligatorio, aula, sede, observaciones, parte_de_id
              FROM cursos
             WHERE catedra_id = %s
             ORDER BY tipo, LENGTH(codigo), codigo, parte_de_id NULLS FIRST, id
            """,
            (catedra_id,),
        ).fetchall()
        comision_ids = [c["id"] for c in cursos if c["tipo"] == "comision"]
        obliga_map = _fetch_obliga_map(conn, comision_ids)
    cursos_resp = [
        CursoResponse(
            **row,
            obliga_a=obliga_map.get(row["id"], []) if row["tipo"] == "comision" else None,
        )
        for row in cursos
    ]
    return CatedraDetail(**catedra, cursos=cursos_resp)


@app.get("/cursos", response_model=list[CursoListItem])
def search_cursos(
    response: Response,
    materia_codigo: int | None = Query(None, description="Filtrar por código de materia"),
    catedra_id: int | None = Query(None, description="Filtrar por id de cátedra"),
    tipo: Literal["teorico", "seminario", "comision"] | None = None,
    dia: str | None = Query(None, description="lunes/martes/.../sabado"),
    sede: str | None = Query(None, description="Prefijo de aula: HY/IN/SI/AV/EC"),
    profesor: str | None = Query(None, description="Substring del nombre del profesor"),
    incluir_obliga: bool = Query(
        False,
        description="Si true, popula `obliga_a` en cada comisión",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[CursoListItem]:
    _set_static_cache(response)
    sql = """
        SELECT cu.id, cu.catedra_id, cu.tipo::text, cu.codigo, cu.dia,
               cu.hora_inicio, cu.hora_fin, cu.profesor, cu.vacantes,
               cu.obligatorio, cu.aula, cu.sede, cu.observaciones, cu.parte_de_id,
               ca.materia_codigo, m.nombre AS materia_nombre
          FROM cursos cu
          JOIN catedras ca ON ca.id = cu.catedra_id
          JOIN materias m  ON m.codigo = ca.materia_codigo
         WHERE (%(materia_codigo)s::int IS NULL OR ca.materia_codigo = %(materia_codigo)s)
           AND (%(catedra_id)s::int IS NULL OR cu.catedra_id = %(catedra_id)s)
           AND (%(tipo)s::text IS NULL OR cu.tipo::text = %(tipo)s)
           AND (%(dia)s::text IS NULL OR cu.dia = %(dia)s)
           AND (%(sede)s::text IS NULL OR cu.sede = %(sede)s)
           AND (%(profesor_pattern)s::text IS NULL OR cu.profesor ILIKE %(profesor_pattern)s)
         ORDER BY cu.catedra_id, cu.tipo, LENGTH(cu.codigo), cu.codigo,
                  cu.parte_de_id NULLS FIRST, cu.id
         LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {
        "materia_codigo": materia_codigo,
        "catedra_id": catedra_id,
        "tipo": tipo,
        "dia": dia,
        "sede": sede,
        "profesor": profesor,
        "profesor_pattern": f"%{profesor}%" if profesor else None,
        "limit": limit,
        "offset": offset,
    }
    with pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        if incluir_obliga:
            comision_ids = [r["id"] for r in rows if r["tipo"] == "comision"]
            obliga_map = _fetch_obliga_map(conn, comision_ids)
        else:
            obliga_map = {}
    return [
        CursoListItem(
            **row,
            obliga_a=(
                obliga_map.get(row["id"], [])
                if incluir_obliga and row["tipo"] == "comision"
                else None
            ),
        )
        for row in rows
    ]


def _request_uses_filters(req: PlanRequest, anuales: set[int]) -> bool:
    """Detecta si el request usa alguna feature Pro (filtros).

    `anuales` son los códigos de las materias del request que se cursan todo el
    año: ahí cátedra y comisión son gratis, porque el alumno ya está cursando una
    comisión concreta y necesita bloquear ese horario para armar el resto.
    """
    # `dias_excluidos` y `solo_con_cupos` son gratis (el FE no los gatea).
    # Pro: franjas, sedes, bache máximo, y cátedra/comisión/profesores/sede por materia.
    if req.franjas_excluidas or req.sedes_permitidas:
        return True
    if req.max_bache_horas is not None:
        return True
    if req.min_dias_semana is not None or req.max_dias_semana is not None:
        return True
    if req.min_horas_dia is not None or req.max_horas_dia is not None:
        return True
    for m in req.materias:
        if m.profesores is not None or m.sede is not None:
            return True
        # Desatar el teórico/seminario de su comisión es Pro incluso en anuales.
        if m.teorico_libre or m.seminario_libre:
            return True
        if m.codigo in anuales:
            continue
        if m.catedra_id is not None or m.comision_codigo is not None:
            return True
    return False


def _materias_anuales(conn, codigos: list[int]) -> set[int]:
    rows = conn.execute(
        "SELECT codigo FROM materias WHERE anual AND codigo = ANY(%s)",
        (codigos,),
    ).fetchall()
    return {r["codigo"] for r in rows}


@app.post("/planes", response_model=PlanResponse)
def post_planes(
    req: PlanRequest,
    user: AuthUser | None = Depends(optional_user),
) -> PlanResponse:
    with pool.connection() as conn:
        is_paid = (
            user is not None and has_active_subscription(conn, user.id)
        )
        # La query de anuales sólo hace falta para decidir el paywall: si el user
        # ya es Pro, o si no mandó cátedra/comisión, nos ahorramos el round-trip.
        anuales: set[int] = set()
        if not is_paid and any(
            m.catedra_id is not None or m.comision_codigo is not None
            for m in req.materias
        ):
            anuales = _materias_anuales(conn, [m.codigo for m in req.materias])

        if _request_uses_filters(req, anuales) and not is_paid:
            # Si el FE deshabilita los filtros para no-Pro, llegar acá con
            # filtros == alguien intentando bypassear el paywall.
            raise HTTPException(
                status_code=403,
                detail=(
                    "Los filtros (franjas, sedes, bache máximo, días por "
                    "semana, horas por día, cátedra, profesores y desatar el "
                    "teórico/seminario de su práctico) son una función Pro. "
                    "Suscribite para usarlos. En materias anuales, cátedra y "
                    "comisión son libres."
                ),
            )
        max_allowed = 100 if is_paid else 15
        if req.max_planes > max_allowed:
            req.max_planes = max_allowed
        return armar_planes(conn, req)
