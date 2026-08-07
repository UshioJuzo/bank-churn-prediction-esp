-- =============================================================================
-- Predicción de abandono bancario - Capa de aterrizaje
-- Destino: Databricks Lakebase Postgres 17 (proyecto: bank-churn-prediction)
-- Base de datos: databricks_postgres   |   Esquema: bank_churn
--
-- FASE 1 de 2. Se ejecuta antes de cargar los datos.
--
-- Aquí no hay ninguna restricción, y es a propósito: si el archivo de origen
-- trae valores malos, tienen que aterrizar y quedar auditables, no ser
-- rechazados en silencio. Las reglas de calidad viven en la fase 2
-- (02_modeled.sql), donde una violación se convierte en un hallazgo
-- documentado en lugar de en un registro perdido.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS bank_churn;

-- -----------------------------------------------------------------------------
-- customers_raw - copia fiel de churn.csv
--
-- Los nombres de columna se normalizan a snake_case porque Postgres pasa a
-- minúsculas los identificadores que no van entrecomillados: mantener
-- "CustomerId" obligaría a entrecomillarlo en cada consulta.
--
-- Los valores no se alteran nunca. Decidimos que esta tabla sea una copia
-- literal del origen para poder demostrar después qué venía del archivo y qué
-- pusimos nosotros.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_churn.customers_raw (
    row_number        INTEGER,
    customer_id       BIGINT,
    surname           TEXT,
    credit_score      INTEGER,
    geography         TEXT,
    gender            TEXT,
    age               INTEGER,
    tenure            INTEGER,
    balance           NUMERIC(14,2),
    num_of_products   INTEGER,
    has_cr_card       SMALLINT,
    is_active_member  SMALLINT,
    estimated_salary  NUMERIC(14,2),
    exited            SMALLINT,

    -- Metadatos de procedencia. Nos permiten responder de dónde salió cada
    -- fila, cuándo entró y desde qué archivo, que es la base de la trazabilidad
    _ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    _source_file      TEXT        NOT NULL,
    _source_url       TEXT
);

COMMENT ON TABLE bank_churn.customers_raw IS
    'Tabla de aterrizaje. Copia inmutable del archivo de origen de Kaggle. Sin restricciones, a propósito.';

-- -----------------------------------------------------------------------------
-- geographies - tabla de consulta
--
-- Es la única normalización honesta que permite este conjunto de datos: tres
-- países fijos. Sirve para poder añadir mañana el código ISO, la moneda o la
-- región sin tener que tocar la tabla de clientes.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_churn.geographies (
    geography_id  SMALLINT PRIMARY KEY,
    country_name  TEXT    NOT NULL UNIQUE,
    iso_code      CHAR(2) NOT NULL UNIQUE
);

INSERT INTO bank_churn.geographies (geography_id, country_name, iso_code) VALUES
    (1, 'France',  'FR'),
    (2, 'Spain',   'ES'),
    (3, 'Germany', 'DE')
ON CONFLICT (geography_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Verificación
-- -----------------------------------------------------------------------------
SELECT table_name
FROM   information_schema.tables
WHERE  table_schema = 'bank_churn'
ORDER  BY table_name;

SELECT * FROM bank_churn.geographies;
