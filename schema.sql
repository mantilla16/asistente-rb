-- =====================================================================
-- ASISTENTE RB — estructura completa
--
-- Aquí solo hay tablas, llaves e índices. Ninguna vista, ningún trigger,
-- ninguna función: toda la lógica vive en Python, donde se puede leer,
-- probar y versionar. Una regla de negocio escondida en un trigger es una
-- regla que nadie revisa.
--
--   createdb asistente_rb
--   psql "$ASISTENTE_DSN" -v ON_ERROR_STOP=1 -f schema.sql
-- =====================================================================

\encoding UTF8
\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS app;


-- =====================================================================
-- USUARIOS Y SESIONES
--
-- Propios de este proyecto. Comparten el diseño con analitica-puc porque
-- está probado, pero no la base: son dos productos y dos padrones.
-- =====================================================================

CREATE TABLE app.usuario (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario        text NOT NULL UNIQUE,
  nombre         text NOT NULL,
  correo         text,
  clave_hash     text NOT NULL,
  rol            text NOT NULL DEFAULT 'MIEMBRO',
  activo         boolean NOT NULL DEFAULT true,
  creado_en      timestamptz NOT NULL DEFAULT now(),
  ultimo_acceso  timestamptz
);

COMMENT ON COLUMN app.usuario.clave_hash IS
  'scrypt$n$r$p$salt_hex$hash_hex — autodescriptivo, ver auth.py';
COMMENT ON COLUMN app.usuario.rol IS
  'ADMIN administra usuarios; MIEMBRO usa el asistente.';
COMMENT ON COLUMN app.usuario.activo IS
  'Se desactiva en vez de borrar: las conversaciones y documentos lo referencian.';

CREATE TABLE app.sesion (
  token_hash  text PRIMARY KEY,
  usuario_id  uuid NOT NULL REFERENCES app.usuario(id) ON DELETE CASCADE,
  creada_en   timestamptz NOT NULL DEFAULT now(),
  expira_en   timestamptz NOT NULL,
  agente      text
);

COMMENT ON TABLE app.sesion IS
  'Se guarda sha256 del token, nunca el token: leer la tabla no permite suplantar.';

CREATE INDEX ix_sesion_usuario ON app.sesion (usuario_id);
CREATE INDEX ix_sesion_expira  ON app.sesion (expira_en);


-- =====================================================================
-- DOCUMENTOS
--
-- El archivo se guarda en disco; aquí queda su huella y su estado. La
-- huella permite detectar que alguien volvió a subir lo mismo, y atar una
-- respuesta a la versión exacta del documento que la sustentó.
-- =====================================================================

CREATE TABLE app.documento (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  propietario_id uuid NOT NULL REFERENCES app.usuario(id) ON DELETE CASCADE,
  nombre        text NOT NULL,
  archivo       text NOT NULL,
  tipo          text NOT NULL,
  bytes         bigint,
  hash_sha256   text NOT NULL,
  estado        text NOT NULL DEFAULT 'PENDIENTE',
  paginas       integer,
  n_fragmentos  integer,
  caracteres    integer,
  error         text,
  compartido    boolean NOT NULL DEFAULT false,
  creado_en     timestamptz NOT NULL DEFAULT now(),
  procesado_en  timestamptz
);

COMMENT ON COLUMN app.documento.estado IS
  'PENDIENTE, EXTRAYENDO, VECTORIZANDO, LISTO, ERROR. Un documento a medio '
  'procesar NO se consulta: respondería sobre una parte sin decirlo.';
COMMENT ON COLUMN app.documento.compartido IS
  'Falso por defecto. Compartir un documento de un cliente tiene que ser un '
  'acto deliberado, nunca el comportamiento por omisión.';
COMMENT ON COLUMN app.documento.error IS
  'Por qué falló el procesamiento, en palabras que el usuario pueda accionar.';

CREATE INDEX ix_documento_dueno ON app.documento (propietario_id, creado_en DESC);
CREATE INDEX ix_documento_hash  ON app.documento (propietario_id, hash_sha256);


-- =====================================================================
-- FRAGMENTOS
--
-- El documento troceado. Cada fragmento guarda de qué página salió para
-- poder citarlo: una respuesta que no se puede rastrear hasta el texto que
-- la sustenta no sirve para trabajar.
--
-- `embedding` va como real[] y no como tipo vectorial: un agente apunta a
-- decenas de documentos, no a millones, y a esa escala comparar todo es
-- exacto, simple de operar e imposible de equivocar. Ver README.
-- =====================================================================

CREATE TABLE app.fragmento (
  id            bigserial PRIMARY KEY,
  documento_id  uuid NOT NULL REFERENCES app.documento(id) ON DELETE CASCADE,
  orden         integer NOT NULL,
  pagina        integer,
  seccion       text,
  texto         text NOT NULL,
  caracteres    integer NOT NULL,
  embedding     real[],
  modelo_embed  text,
  tsv           tsvector
);

COMMENT ON COLUMN app.fragmento.tsv IS
  'Índice de texto en español. Encuentra lo que el parecido semántico pierde: '
  'un NIT, un número de factura, un nombre propio.';

CREATE INDEX ix_fragmento_doc ON app.fragmento (documento_id, orden);
CREATE INDEX ix_fragmento_tsv ON app.fragmento USING gin (tsv);


-- =====================================================================
-- AGENTES
--
-- Un agente es un encargo permanente: unas instrucciones, un modelo y un
-- conjunto de documentos. Sin documentos asociados consulta todo lo del
-- dueño; con ellos, se limita a esos -- que es lo que lo vuelve preciso.
-- =====================================================================

CREATE TABLE app.agente (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  propietario_id uuid NOT NULL REFERENCES app.usuario(id) ON DELETE CASCADE,
  nombre         text NOT NULL,
  descripcion    text,
  instrucciones  text NOT NULL DEFAULT '',
  modelo         text,
  temperatura    numeric(3,2) NOT NULL DEFAULT 0.30,
  fragmentos     smallint NOT NULL DEFAULT 4,
  compartido     boolean NOT NULL DEFAULT false,
  activo         boolean NOT NULL DEFAULT true,
  creado_en      timestamptz NOT NULL DEFAULT now(),
  actualizado_en timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN app.agente.temperatura IS
  'Baja por defecto: para consultar documentos se quiere fidelidad, no '
  'creatividad. Se sube a mano cuando el agente es para redactar.';
COMMENT ON COLUMN app.agente.fragmentos IS
  'Cuántos fragmentos se le ponen delante al modelo. Más contexto no es '
  'mejor: en CPU lo que cuesta tiempo son los tokens del prompt, y el ruido '
  'tapa la señal tanto como la aporta. Medido: ocho fragmentos de una tabla '
  'de cifras tardaron 288 segundos solo en leerse.';

CREATE INDEX ix_agente_dueno ON app.agente (propietario_id, creado_en DESC);

CREATE TABLE app.agente_documento (
  agente_id    uuid NOT NULL REFERENCES app.agente(id) ON DELETE CASCADE,
  documento_id uuid NOT NULL REFERENCES app.documento(id) ON DELETE CASCADE,
  PRIMARY KEY (agente_id, documento_id)
);


-- =====================================================================
-- CONVERSACIONES
-- =====================================================================

CREATE TABLE app.conversacion (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id    uuid NOT NULL REFERENCES app.usuario(id) ON DELETE CASCADE,
  agente_id     uuid REFERENCES app.agente(id) ON DELETE SET NULL,
  titulo        text NOT NULL DEFAULT 'Nueva conversación',
  archivada     boolean NOT NULL DEFAULT false,
  creada_en     timestamptz NOT NULL DEFAULT now(),
  actualizada_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_conversacion_usuario
  ON app.conversacion (usuario_id, archivada, actualizada_en DESC);

CREATE TABLE app.mensaje (
  id              bigserial PRIMARY KEY,
  conversacion_id uuid NOT NULL REFERENCES app.conversacion(id) ON DELETE CASCADE,
  rol             text NOT NULL,
  texto           text NOT NULL,
  citas           jsonb,
  modelo          text,
  ms              integer,
  tokens_salida   integer,
  creado_en       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN app.mensaje.rol IS 'usuario | asistente | sistema';
COMMENT ON COLUMN app.mensaje.citas IS
  'Los fragmentos que se le pusieron delante al modelo para esta respuesta. '
  'Sin esto no hay forma de saber sobre qué contestó, y una respuesta que no '
  'se puede rastrear no sirve para trabajar.';

CREATE INDEX ix_mensaje_conv ON app.mensaje (conversacion_id, id);


-- =====================================================================
-- BITÁCORA
--
-- Quién hizo qué. Sirve para seguimiento y para responder la pregunta
-- incómoda: qué documentos vio esta persona y qué le preguntó al modelo.
-- =====================================================================

CREATE TABLE app.bitacora (
  id          bigserial PRIMARY KEY,
  usuario     text,
  accion      text NOT NULL,
  entidad     text,
  entidad_id  text,
  detalle     jsonb,
  ip          text,
  agente_http text,
  estado      integer,
  ms          integer,
  creado_en   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_bitacora_fecha   ON app.bitacora (creado_en DESC);
CREATE INDEX ix_bitacora_usuario ON app.bitacora (usuario, creado_en DESC);

COMMIT;


-- =====================================================================
-- VERIFICACIÓN
-- =====================================================================

SELECT table_name,
       (SELECT count(*) FROM information_schema.columns c
         WHERE c.table_schema='app' AND c.table_name=t.table_name) AS columnas
  FROM information_schema.tables t
 WHERE table_schema='app'
 ORDER BY table_name;
