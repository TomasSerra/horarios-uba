# Backend — FastAPI + Postgres

API que sirve materias/cátedras/cursos y arma planes de cursada. Scraper aparte que siembra la DB. Auth con Firebase, pagos con Mercado Pago.

## Estructura

```
backend/
  api/
    main.py       endpoints + lifespan + CORS (incluye /carreras y /materias filtradas por carrera)
    auth.py       dependency current_user / optional_user (firebase-admin)
    me.py         GET /me (perfil + subscription) + PATCH /me/profile (elegir carrera)
    subs.py       helper has_active_subscription + _record_payment
    pagos.py      /pagos/checkout + webhook de Mercado Pago
    favoritos.py  CRUD de favoritos (Pro)
    planes.py     algoritmo de armado (producto cartesiano + filtros + overlap check)
    models.py     pydantic models compartidos
    db.py         psycopg connection pool
  scraper/
    main.py       entrypoint
    discover.py   listado de materias/cátedras
    parse.py      parsing HTML del sistema académico
    db.py         inserts idempotentes
    vigencia.py   guardas del sweep (lógica pura)
    http.py       cliente con retries/delay
    config.py
  schema.sql      DDL ejecutado al crear la DB
  Dockerfile      uvicorn --reload --reload-dir /app/api
  requirements.txt
  firebase-sa.json  (gitignored) service account de Firebase Admin para dev local
```

## Cómo corre

- `uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/api`. El volumen `./backend/api:/app/api` permite hot reload sin rebuild.
- Conexión via `DATABASE_URL` (psycopg pool, abierto en el lifespan).
- Auth: `_initialize_firebase()` ([api/auth.py](api/auth.py)) intenta en orden: (1) `GOOGLE_APPLICATION_CREDENTIALS` como path a un JSON (dev local en Docker, montado en `/run/secrets/firebase-sa.json`); (2) `_credentials_from_env()`, que arma el service account desde envs sueltas `FIREBASE_PROJECT_ID` / `FIREBASE_PRIVATE_KEY` / `FIREBASE_CLIENT_EMAIL` (+ opcionales) — este es el camino en **Vercel**, que no tiene filesystem persistente; (3) ADC puro como fallback.

## Tests

- `make install-test-deps` crea un venv en `backend/.venv` e instala pytest + deps (una vez).
- `make test` corre la suite en `backend/tests/`. Tests puros: sin Docker, sin DB real, sin red. Tarda <1s.
- `make install-hooks` cablea el hook pre-commit que corre los tests antes de cada commit. Bloquea el commit si alguno falla y lista cuáles fueron.
- Cobertura actual: algoritmo de planes (todos los filtros + combinaciones), paywall Pro (`/planes` y `_request_uses_filters`), auth (Firebase mockeado), firma HMAC del webhook de MP, suscripciones (`has_active_subscription`, `_record_payment`, renovaciones, idempotencia), favoritos (gating Pro y aislamiento entre usuarios), guardas del sweep del scraper (`evaluar_sweep`).
- `FakeConn` no ejecuta SQL, así que los filtros que viven en el `WHERE` (como el de vigencia) sólo se pueden testear afirmando que el predicado sigue en el query. El filtrado real se verifica contra la DB local.
- DB mockeada con `FakeConn` en `backend/tests/conftest.py` (helpers `make_comision_row`, `make_obliga_row`, `setup_planes_db`). Firebase mockeado parcheando `_apps` antes del import + `monkeypatch` de `fb_auth.verify_id_token`.

## Load testing (k6)

Tests de carga en `backend/loadtest/` que le pegan a `POST /planes` **en producción** (es read-only y anónimo: no escribe datos ni toca Mercado Pago). Necesitan [k6](https://k6.io) instalado (`brew install k6`). Apuntan vía la env `API`; reparto fijo 80% planes de 3 materias / 20% de 4, y la mitad de cada grupo manda `solo_con_cupos` + excluir sábado (ambos filtros gratis, no gatean Pro — por eso corre todo sin token).

```
backend/loadtest/
  config.js      helpers + métricas custom + generador de reporte (compartido)
  realistic.js   50 usuarios escalonados en una ventana (~10-30s entre arribos)
  burst.js       pico de N concurrentes (default 100) en 4 olas
  reportes/      salidas (gitignored), con fecha en el nombre
```

| Comando | Qué hace |
| --- | --- |
| `API=https://planify-uni-api.vercel.app k6 run realistic.js` | Escenario realista. `VENTANA=60` achica la ventana de arribos (prueba rápida). |
| `API=... k6 run burst.js` | Pico de concurrencia. `VUS=200` sube el pico. |
| `API=... CARRERA=profesorado-psicologia k6 run realistic.js` | Otra carrera (default `licenciatura-psicologia`; ver `GET /carreras` para los slugs). |

Cada corrida deja en `reportes/` un `<escenario>-<fecha>.html` (veredicto PASÓ/FALLÓ + por qué falló con desglose de errores por código, sección Resumen simple y Detalle completo) y el `.json` crudo. Lo que más vale mirar en vivo: el gráfico de *connections* en Neon y los logs de función en Vercel (504/timeouts). El cuello de botella esperable no es CPU sino conexiones a Neon y cold starts de Vercel.

## Hosting

API en **Vercel** (Free) como FastAPI serverless ([docs](https://vercel.com/docs/frameworks/backend/fastapi)) — cada request es una invocación de función, no hay proceso uvicorn persistente. DB en **Neon** Postgres; `DATABASE_URL` debe apuntar al **endpoint pooled** (host con `-pooler`, PgBouncer) porque en serverless cada instancia abre su propio pool y las conexiones directas se agotan. Secrets del API en Vercel: `DATABASE_URL`, las `FIREBASE_*` (ver Auth), `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`, `APP_URL`, `APP_URL_BACKEND`. El `Dockerfile` quedó solo para dev local (Docker Compose); Vercel no lo usa.

## Endpoints

| Método | Path | Auth | Notas |
| --- | --- | --- | --- |
| GET | `/health` | — | Healthcheck DB. |
| GET | `/carreras` | — | Lista de carreras con sus sedes. |
| GET | `/materias?q=&carrera=` | — | Lista de materias con filtro substring, opcionalmente acotada a una carrera. Devuelve `cant_catedras` (histórico) y `cant_catedras_vigentes`. |
| GET | `/materias/{codigo}` | — | Materia + cátedras. |
| GET | `/materias/{codigo}/opciones` | — | Materia + cátedras + profesores únicos. Incluye cátedras no vigentes con `vigente=false`: lo consumen `MateriaCard.tsx` (filtra) y `ReviewDialog.tsx` (no filtra). |
| GET | `/catedras/{id}` | — | Cátedra + todos sus cursos con `obliga_a` resuelto. |
| GET | `/cursos?...&incluir_obliga=` | — | Búsqueda flexible. |
| POST | `/planes` | `optional_user` | Si el usuario es Pro, aplica filtros completos y cap 100. Si no, anula filtros y capea a 15. |
| GET | `/me` | `current_user` | Perfil (carrera) + estado de suscripción en un solo payload. |
| PATCH | `/me/profile` | `current_user` | Setea la carrera elegida del usuario. |
| POST | `/pagos/checkout` | `current_user` | Crea preferencia de MP, devuelve `init_point`. |
| GET | `/pagos/{external_reference}/status` | — | Polling público de status (idempotente). |
| POST | `/pagos/webhook` | — | Webhook de MP (valida firma `MP_WEBHOOK_SECRET`). |
| GET/POST/DELETE | `/favoritos` | `current_user` | CRUD; gateado a Pro adentro. |

CORS: `localhost:5173` y `localhost:3000` + `APP_URL`. Sumar nuevos orígenes en `_allowed_origins` ([api/main.py](api/main.py)). **El `add_middleware(CORSMiddleware, ...)` va después de `log_unhandled` a propósito** (Starlette apila el último agregado como el más externo): si CORS queda adentro, los 500 salen sin `Access-Control-Allow-Origin`, el navegador los bloquea y el front ve un `TypeError` de red en vez del error. Cubierto por `tests/test_error_logging.py`.

## Auth (firebase-admin)

[api/auth.py](api/auth.py):

- `firebase_admin.initialize_app()` se llama una vez al import. Usa Application Default Credentials → `GOOGLE_APPLICATION_CREDENTIALS`.
- `current_user(authorization: str = Header(...)) -> AuthUser`: parsea `Bearer <idToken>`, llama `fb_auth.verify_id_token(token)`, devuelve `AuthUser(id=decoded["uid"])`. Tira 401 ante token inválido / expirado.
- `optional_user`: devuelve `None` si no hay header, sino delega a `current_user`.
- `AuthUser.id` es el `uid` de Firebase como string opaco. Se almacena en columnas llamadas `clerk_user_id` (nombre histórico).

## Vigencia de la oferta

`catedras.vigente` separa el **catálogo histórico** (todo lo que existió alguna vez) de la **oferta del cuatrimestre actual**. Es un soft flag: **el scraper nunca borra materias, cátedras ni cursos**.

- **Armado de planes** → sólo vigentes. El filtro vive en el `JOIN` de `_fetch_opciones_por_materia` ([api/planes.py](api/planes.py)), más `/carreras` (sedes) y `cant_catedras_vigentes` en `/materias`.
- **Reseñas** → sin filtrar, a propósito. Se puede ver y dejar reseñas de cátedras y materias discontinuadas: es un registro histórico de una cursada pasada. Los `cursos` viejos se conservan porque `upsert_review` valida contra ellos el profesor elegido.
- `/materias/{cod}/opciones` devuelve **ambas** con un flag `vigente`; filtra cada consumidor del FE (`MateriaCard` sí, `ReviewDialog` no).

Estos endpoints se sirven con `_set_static_cache` (`public, max-age=1200, stale-while-revalidate=2400`), así que el FE les manda `?v=DATA_VERSION` para poder saltear el cache del browser y del CDN en un deploy. Si agregás un campo que el FE va a dar por hecho, hay que bumpear `DATA_VERSION` en `frontend/src/lib/api.ts` — si no, durante la ventana de cache los usuarios reciben el payload viejo sin el campo.

El sweep (`dar_de_baja_ausentes` en [scraper/main.py](scraper/main.py)) corre al final de cada corrida completa y marca `vigente = FALSE` lo que no apareció en el índice. El set de referencia es el del **índice**, no el de las cátedras guardadas con éxito: que falle la página de detalle de una cátedra no significa que se haya dejado de dictar.

Las guardas viven en [scraper/vigencia.py](scraper/vigencia.py) (`evaluar_sweep`, lógica pura, testeada en `tests/test_scraper_vigencia.py`). Entre el 1er y el 2do cuatrimestre la fuente deja de publicar datos, y una corrida contra un índice vacío o a medio cargar no puede vaciar la app:

| Situación | Qué hace |
| --- | --- |
| Índice vacío (200 con HTML cambiado) | **No barre ni con `--force-sweep`**, exit 1 |
| Error de red en el índice (404/500) | No barre, exit 1 |
| Índice < 50% de las vigentes actuales | No barre, exit 1. Se destraba con `--force-sweep` |
| Corrida con `--limit` o `--catedra` | No barre (procesan un subconjunto) |

`SCRAPER_MIN_SWEEP_RATIO` cambia el umbral. `--dry-run-sweep` lista qué se daría de baja sin scrapear ni escribir: es read-only y seguro contra producción.

**Rollback**: `UPDATE catedras SET vigente = TRUE;`. Como no se borra nada, es total e instantáneo.

## Generador de planes ([api/planes.py](api/planes.py))

1. Por materia, traer todas las opciones (`comision + obligas`).
2. Filtrar por `catedra_id` si vino, por profesores permitidos (semántica: `None` = todos, `[]` = ninguno → 0 opciones, lista = subset), y por restricciones de día/franja/sede.
3. Si alguna materia queda sin opciones válidas → response con `materias_sin_opciones`.
4. `itertools.product(*opciones_validas)` y para cada combo chequear solapamientos. Cortar al alcanzar `max_planes`.

Notas:
- `total_generados` = combos evaluados hasta el corte (no = combos totales del producto).
- `_hay_solapamiento` opera sobre la lista plana de cursos del combo.
- El campo `profesores` en `MateriaSeleccionada` es `list[str] | None` con la semántica triple descrita.

## Reglas de modificación

- Tipos de respuesta usan Pydantic v2. Si agregás campos, actualizar también `frontend/src/lib/types.ts`.
- Las queries usan psycopg `dict_row` (filas son dicts). Mantener ese estilo.
- Idempotencia en scraper: cualquier fix debe seguir siendo seguro de re-correr (`make scrape`).
- **El scraper no borra datos.** Dar de baja oferta se hace con `catedras.vigente`, nunca con `DELETE`. Un cambio que borre materias, cátedras o cursos huérfanos se lleva puestas las reseñas (por el `ON DELETE CASCADE` de `catedra_reviews`) o rompe la validación de profesor de `upsert_review`. Ver [Vigencia de la oferta](#vigencia-de-la-oferta).
- La columna `clerk_user_id` en `subscriptions` y `favorite_plans` se llama así por historia (se planeó usar Clerk). Hoy almacena el `uid` de Firebase. No renombrar — el cambio requeriría una migración y no aporta nada funcional.
- Hot reload solo recoge cambios en `/app/api`. Cambios al scraper requieren re-build del container.
- **Tests obligatorios**: toda función nueva del backend que (a) implemente lógica de negocio (no glue puro ni queries triviales), (b) afecte el paywall / suscripciones / pagos, o (c) agregue un filtro nuevo al generador de planes, **debe** venir con tests en `backend/tests/`. El hook pre-commit los corre antes de cada commit — si rompés algo o no testeás algo nuevo crítico, el commit no entra. En particular:
  - **Nuevo filtro en `PlanRequest` / `MateriaSeleccionada`** → tests del filtro solo + tests de combinación con al menos otros 2 filtros existentes en `tests/test_planes_armar.py`. Si el filtro es feature Pro, también extender `_request_uses_filters` y agregar el campo a `tests/test_paywall.py`.
  - **Cambio en `has_active_subscription` o `_record_payment`** → tests de las nuevas ramas en `tests/test_subs.py`.
  - **Nuevo endpoint gateado por Pro** → tests de los 3 estados (anónimo, free, Pro) en el archivo de tests que corresponda.
  - **Cambio en la firma HMAC del webhook MP** → extender `tests/test_pagos_signature.py`.

## Cambios típicos

- **Nuevo endpoint**: agregar handler en `api/main.py` o crear router en archivo aparte y `app.include_router(...)`.
- **Nuevo filtro en `/planes`**: extender `PlanRequest`, aplicarlo en `armar_planes` antes del producto.
- **Schema change**: editar `schema.sql`. Para datos locales hay que `make reset` (no hay migraciones — la app es lo bastante chica para no necesitar Alembic todavía).
