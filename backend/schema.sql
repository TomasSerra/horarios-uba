-- Schema de PostgreSQL para horarios de la Facultad de Psicología (UBA).
-- Ejecutar contra una DB recién creada:  psql horarios < schema.sql

-- Carreras de la facultad. El slug se mapea desde el id del tab del HTML de
-- academica.psi.uba.ar (PS/PR/LM/TE) en el scraper.
CREATE TABLE IF NOT EXISTS carreras (
    slug        TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

INSERT INTO carreras (slug, nombre, sort_order) VALUES
    ('licenciatura-psicologia',    'Licenciatura en Psicología',          1),
    ('profesorado-psicologia',     'Profesorado en Psicología',           2),
    ('licenciatura-musicoterapia', 'Licenciatura en Musicoterapia',       3),
    ('licenciatura-terap-ocup',    'Licenciatura en Terapia Ocupacional', 4)
ON CONFLICT (slug) DO NOTHING;

CREATE TABLE IF NOT EXISTS materias (
    codigo  INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL,
    carrera TEXT REFERENCES carreras(slug)
);

-- Para DBs preexistentes (Neon) que ya tenían materias sin la columna.
ALTER TABLE materias ADD COLUMN IF NOT EXISTS carrera TEXT REFERENCES carreras(slug);

CREATE INDEX IF NOT EXISTS idx_materias_carrera ON materias(carrera);

-- `vigente` marca si la cátedra figura en la oferta del cuatrimestre actual.
-- El scraper la apaga (nunca borra) cuando desaparece del índice de la fuente,
-- y la vuelve a prender sola si reaparece. Las cátedras no vigentes se excluyen
-- del armado de planes pero siguen visibles en reseñas: los `cursos` viejos se
-- conservan justamente para eso (validar el profesor de una reseña).
CREATE TABLE IF NOT EXISTS catedras (
    id              INTEGER PRIMARY KEY,
    materia_codigo  INTEGER NOT NULL REFERENCES materias(codigo),
    numero          TEXT,
    titular         TEXT,
    cuatrimestre    TEXT,
    vigente         BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at    TIMESTAMPTZ
);

-- Para DBs preexistentes (Neon). DEFAULT TRUE deja toda fila existente vigente,
-- así que agregar la columna no cambia el comportamiento de la app hasta que el
-- scraper corra su primer sweep.
ALTER TABLE catedras ADD COLUMN IF NOT EXISTS vigente BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE catedras ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_curso') THEN
        CREATE TYPE tipo_curso AS ENUM ('teorico', 'seminario', 'comision');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS cursos (
    id              BIGSERIAL PRIMARY KEY,
    catedra_id      INTEGER NOT NULL REFERENCES catedras(id) ON DELETE CASCADE,
    tipo            tipo_curso NOT NULL,
    codigo          TEXT NOT NULL,
    dia             TEXT,
    hora_inicio     TIME,
    hora_fin        TIME,
    profesor        TEXT,
    vacantes        INTEGER,
    obligatorio     TEXT,
    aula            TEXT,
    sede            TEXT,
    observaciones   TEXT
    -- (catedra_id, tipo, codigo) NO es único: la fuente puede listar dos
    -- teóricos "I" con co-titulares en bloques consecutivos.
);

CREATE INDEX IF NOT EXISTS idx_cursos_dia       ON cursos(dia);
CREATE INDEX IF NOT EXISTS idx_cursos_catedra   ON cursos(catedra_id);
CREATE INDEX IF NOT EXISTS idx_catedras_materia ON catedras(materia_codigo);
-- Índice parcial para las lecturas del armado de planes, que siempre filtran por
-- vigencia. El índice completo de arriba sigue sirviendo a las queries de reseñas,
-- que a propósito NO filtran.
CREATE INDEX IF NOT EXISTS idx_catedras_materia_vigente
    ON catedras(materia_codigo) WHERE vigente;

-- Relación many-to-many: una comisión obliga a 0, 1 o 2 cursos (teórico y/o
-- seminario) de la misma cátedra. Resuelta por el scraper a partir del campo
-- cursos.obligatorio. Casos como "I - A", "J - I" (orden invertido) o "IV - II"
-- (dos teóricos) se modelan uniformemente como filas en esta tabla.
CREATE TABLE IF NOT EXISTS comision_obliga (
    comision_id BIGINT NOT NULL REFERENCES cursos(id) ON DELETE CASCADE,
    obliga_a_id BIGINT NOT NULL REFERENCES cursos(id) ON DELETE CASCADE,
    PRIMARY KEY (comision_id, obliga_a_id),
    CHECK (comision_id <> obliga_a_id)
);

CREATE INDEX IF NOT EXISTS idx_comision_obliga_obliga_a ON comision_obliga(obliga_a_id);

-- Subscripciones: registro de pagos vía Mercado Pago. clerk_user_id es FK lógica
-- (no hay tabla users propia: Firebase Auth es la fuente de verdad). El nombre
-- "clerk_user_id" es histórico y se mantiene por compatibilidad: hoy almacena
-- el uid de Firebase como string opaco. mp_external_reference y mp_payment_id
-- UNIQUE dan idempotencia ante webhook duplicado (MP reintenta y a veces manda
-- el mismo payment con distinto request).
CREATE TABLE IF NOT EXISTS subscriptions (
    id                     BIGSERIAL PRIMARY KEY,
    clerk_user_id          TEXT NOT NULL,
    valid_from             TIMESTAMPTZ NOT NULL,
    valid_until            TIMESTAMPTZ NOT NULL,
    mp_payment_id          TEXT UNIQUE,
    mp_external_reference  TEXT UNIQUE,
    amount_ars             NUMERIC(10, 2),
    -- Comisión que se queda MP (suma de fee_details con fee_payer=collector) y
    -- neto acreditado (transaction_details.net_received_amount). mp_fee_details
    -- guarda el array crudo para desglosar después sin re-consultar la API de MP.
    mp_fee_ars             NUMERIC(10, 2),
    mp_net_received_ars    NUMERIC(10, 2),
    mp_fee_details         JSONB,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS mp_fee_ars NUMERIC(10, 2);
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS mp_net_received_ars NUMERIC(10, 2);
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS mp_fee_details JSONB;

CREATE INDEX IF NOT EXISTS idx_subs_user_until
    ON subscriptions(clerk_user_id, valid_until DESC);

-- Planes guardados como favoritos por usuarios Pro. plan_data almacena el Plan
-- tal cual lo devuelve /planes (snapshot en JSON: los cursos cambian entre
-- cuatrimestres, no tiene sentido FKearlo a cursos.id). clerk_user_id: mismo
-- comentario que en subscriptions — hoy guarda el uid de Firebase.
CREATE TABLE IF NOT EXISTS favorite_plans (
    id              BIGSERIAL PRIMARY KEY,
    clerk_user_id   TEXT NOT NULL,
    plan_data       JSONB NOT NULL,
    -- Snapshot de los filtros (días excluidos, franjas, sedes, selección por
    -- materia) que el usuario tenía al guardar. Se muestran en la card de la
    -- página de favoritos.
    filters_data    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_favorites_user
    ON favorite_plans(clerk_user_id, created_at DESC);

-- Mapeo external_reference -> init_point para el QR de pago mobile. El QR
-- codifica una URL nuestra (/pago-qr/:ref) en vez de la init_point directa de
-- MP — así la app de Mercado Pago no procesa el QR in-app (caso en que el
-- webhook nunca se dispara) y queda obligado el flujo por navegador.
CREATE TABLE IF NOT EXISTS pending_checkouts (
    external_reference TEXT PRIMARY KEY,
    init_point         TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Perfil mínimo del usuario logueado (Firebase uid). Se materializa una fila
-- cuando el usuario elige carrera o setea su nombre por primera vez. Ambas
-- columnas son nullables: se pide nombre primero y carrera después, así que la
-- fila puede existir con solo una de las dos.
CREATE TABLE IF NOT EXISTS user_profile (
    uid         TEXT PRIMARY KEY,
    carrera     TEXT REFERENCES carreras(slug),
    nombre      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Para DBs preexistentes (Neon) creadas antes de tener nombre / con carrera NOT NULL.
ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS nombre TEXT;
ALTER TABLE user_profile ALTER COLUMN carrera DROP NOT NULL;

-- Reseñas de cátedras dejadas por la comunidad. Se atan a catedra_id (PK entero
-- estable que viene de la fuente; el scraper hace upsert y nunca borra cátedras,
-- así que las reseñas sobreviven entre cuatrimestres). Una reseña por usuario por
-- cátedra (UNIQUE). clerk_user_id: mismo comentario histórico que en las otras
-- tablas — hoy guarda el uid de Firebase. Las reseñas se muestran anónimas: el
-- uid sólo sirve para el UNIQUE y para que el autor edite/borre la suya.
CREATE TABLE IF NOT EXISTS catedra_reviews (
    id             BIGSERIAL PRIMARY KEY,
    catedra_id     INTEGER NOT NULL REFERENCES catedras(id) ON DELETE CASCADE,
    clerk_user_id  TEXT NOT NULL,
    -- Nota de la CÁTEDRA (obligatoria).
    rating         SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment        TEXT,
    -- Profesor reseñado (de las comisiones de la cátedra) y su nota, opcionales:
    -- o van los dos o ninguno. Independiente del rating de la cátedra.
    profesor       TEXT,
    profesor_rating SMALLINT CHECK (profesor_rating BETWEEN 1 AND 5),
    anio           SMALLINT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (catedra_id, clerk_user_id),
    CHECK ((profesor IS NULL) = (profesor_rating IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_catedra_reviews_catedra
    ON catedra_reviews(catedra_id, created_at DESC);
