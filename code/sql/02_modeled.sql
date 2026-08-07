-- =============================================================================
-- Predicción de abandono bancario - Capa modelada
-- Destino: Databricks Lakebase Postgres 17 (proyecto: bank-churn-prediction)
-- Base de datos: databricks_postgres   |   Esquema: bank_churn
--
-- FASE 2 de 2. Se ejecuta DESPUÉS de cargar customers_raw y de pasar las ocho
-- verificaciones de datos (V1 a V8) del notebook 01.
--
-- Los límites de los CHECK que hay abajo son expectativas, no hechos
-- comprobados. Hay que ajustarlos a los rangos observados antes de ejecutar.
--
-- Ajustes pendientes tras la verificación:
--   V1  ¿customer_id es único?          -> si no, la PRIMARY KEY tendría que
--                                          pasar a ser una clave sustituta
--   V3  valores distintos de geography
--       y de gender                     -> ajustar las filas de la tabla de
--                                          consulta y el CHECK de gender
--   V4  rangos reales                   -> ajustar los límites de los CHECK
--   V5  ¿hay nulos?                     -> habría que relajar las cláusulas
--                                          NOT NULL
-- =============================================================================

-- -----------------------------------------------------------------------------
-- customers - tipada, con clave y con restricciones
--
-- surname no se propaga desde la tabla de aterrizaje, y es deliberado: la
-- restricción de privacidad la impone el esquema, no la disciplina de quien
-- escribe el código. Una columna que no existe no se puede filtrar por
-- descuido.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_churn.customers (
    customer_id       BIGINT        PRIMARY KEY,
    geography_id      SMALLINT      NOT NULL REFERENCES bank_churn.geographies,
    gender            TEXT          NOT NULL CHECK (gender IN ('Male','Female')),
    age               SMALLINT      NOT NULL CHECK (age BETWEEN 18 AND 120),
    tenure            SMALLINT      NOT NULL CHECK (tenure BETWEEN 0 AND 10),
    credit_score      SMALLINT      NOT NULL CHECK (credit_score BETWEEN 300 AND 900),
    balance           NUMERIC(14,2) NOT NULL CHECK (balance >= 0),
    estimated_salary  NUMERIC(14,2) NOT NULL CHECK (estimated_salary >= 0),
    num_of_products   SMALLINT      NOT NULL CHECK (num_of_products BETWEEN 1 AND 4),
    has_cr_card       BOOLEAN       NOT NULL,
    is_active_member  BOOLEAN       NOT NULL,
    exited            BOOLEAN       NOT NULL,
    _loaded_at        TIMESTAMPTZ   NOT NULL DEFAULT now()
);

COMMENT ON TABLE bank_churn.customers IS
    'Registro operacional de clientes. surname excluido a propósito: privacidad impuesta por el esquema.';

CREATE INDEX IF NOT EXISTS idx_customers_geography ON bank_churn.customers (geography_id);
CREATE INDEX IF NOT EXISTS idx_customers_exited    ON bank_churn.customers (exited);

-- -----------------------------------------------------------------------------
-- model_runs - procedencia, no analítica
--
-- No guarda ninguna métrica de evaluación, y es a propósito: esas viven en
-- gold.model_metrics (Delta), que es donde está el público que las lee. Lo que
-- se queda aquí es lo que responde a una pregunta operativa desde el CRM:
-- "¿por qué cambió el nivel de riesgo de esta clienta entre septiembre y
-- noviembre?"
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_churn.model_runs (
    model_run_id        BIGSERIAL    PRIMARY KEY,
    model_name          TEXT         NOT NULL,
    model_version       TEXT         NOT NULL,
    decision_threshold  NUMERIC(5,4) NOT NULL CHECK (decision_threshold BETWEEN 0 AND 1),
    trained_at          TIMESTAMPTZ  NOT NULL,
    notes               TEXT,
    UNIQUE (model_name, model_version)
);

COMMENT ON TABLE bank_churn.model_runs IS
    'Procedencia de cada ejecución de puntuación. Las métricas de evaluación se excluyen a propósito.';

-- -----------------------------------------------------------------------------
-- customer_predictions - destino del reverse ETL, lo consume el equipo de
-- retención
--
-- La clave primaria es compuesta porque el historial es de solo añadido: una
-- fila por cliente y por ejecución. Así se puede reconstruir qué se predijo en
-- cada momento en lugar de sobrescribir el pasado.
--
-- Los cortes de risk_level se deciden en el notebook 05 con el método que
-- fijamos de antemano: mandan la capacidad operativa de la campaña y, como
-- comprobación, el umbral de coste esperado.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_churn.customer_predictions (
    customer_id        BIGINT       NOT NULL REFERENCES bank_churn.customers,
    model_run_id       BIGINT       NOT NULL REFERENCES bank_churn.model_runs,
    churn_probability  NUMERIC(6,5) NOT NULL CHECK (churn_probability BETWEEN 0 AND 1),
    predicted_class    BOOLEAN      NOT NULL,
    risk_level         TEXT         NOT NULL CHECK (risk_level IN ('bajo','medio','alto')),
    scored_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, model_run_id)
);

COMMENT ON TABLE bank_churn.customer_predictions IS
    'Destino del reverse ETL. Solo se añade: una fila por cliente y ejecución de puntuación.';

CREATE INDEX IF NOT EXISTS idx_pred_risk ON bank_churn.customer_predictions (risk_level);
CREATE INDEX IF NOT EXISTS idx_pred_prob ON bank_churn.customer_predictions (churn_probability DESC);

-- -----------------------------------------------------------------------------
-- Última puntuación de cada cliente. Es lo que lee la aplicación de Streamlit
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW bank_churn.v_latest_predictions AS
SELECT DISTINCT ON (customer_id)
       customer_id,
       model_run_id,
       churn_probability,
       predicted_class,
       risk_level,
       scored_at
FROM   bank_churn.customer_predictions
ORDER  BY customer_id, scored_at DESC;

-- -----------------------------------------------------------------------------
-- Verificación
-- -----------------------------------------------------------------------------
SELECT table_name, table_type
FROM   information_schema.tables
WHERE  table_schema = 'bank_churn'
ORDER  BY table_type, table_name;
