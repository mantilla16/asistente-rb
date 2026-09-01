-- =====================================================================
-- TABLAS: hojas de cálculo como DATOS, no como texto
--
-- Un Excel troceado en fragmentos de texto no se puede consultar: el
-- modelo ve cuatro trozos de setecientos y responde "hay 3 cuentas"
-- cuando hay 85. No es un problema de contexto, es que contar, listar y
-- sumar son operaciones sobre datos, no sobre lenguaje.
--
-- Así que la hoja se guarda tal cual -- columnas y filas -- y las
-- preguntas de conteo, listado o total se responden CALCULÁNDOLAS. Al
-- modelo le llega el resultado ya calculado, para que lo redacte.
--
--   psql "$ASISTENTE_DSN" -v ON_ERROR_STOP=1 -f 02_tablas.sql
-- =====================================================================

\encoding UTF8
\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE app.tabla (
  id            bigserial PRIMARY KEY,
  documento_id  uuid NOT NULL REFERENCES app.documento(id) ON DELETE CASCADE,
  hoja          text NOT NULL,
  columnas      jsonb NOT NULL,
  filas         jsonb NOT NULL,
  n_filas       integer NOT NULL,
  truncada      boolean NOT NULL DEFAULT false
);

COMMENT ON TABLE app.tabla IS
  'Una hoja de cálculo tal como está: encabezados y filas. Sobre esto se '
  'calculan los conteos y totales, en vez de pedírselos a un modelo que '
  'solo vería una muestra.';
COMMENT ON COLUMN app.tabla.truncada IS
  'La hoja superó el tope de filas que se guardan. Cuando es cierto, todo '
  'conteo que salga de aquí es un piso y NO el total: se declara.';

CREATE INDEX ix_tabla_doc ON app.tabla (documento_id);

COMMIT;

SELECT 'app.tabla creada' AS resultado;
