-- =============================================================================
-- Predicción de abandono bancario - Desmontaje
-- Destino: Databricks Lakebase Postgres 17 (proyecto: bank-churn-prediction)
--
-- DESTRUCTIVO. Elimina el esquema bank_churn entero y todas sus filas.
-- Reconstruirlo después lleva unos dos minutos:
--     00_teardown.sql  ->  01_landing.sql  ->  notebook 01 parte A  ->  02_modeled.sql
--
-- Alternativa más segura: en lugar de borrar, crear una rama de Lakebase,
-- experimentar en ella y después eliminarla. La rama de producción no se toca:
--     databricks postgres create-branch projects/bank-churn-prediction sandbox \
--       --json '{"spec": {"source_branch": "projects/bank-churn-prediction/branches/production", "ttl": "86400s"}}'
-- =============================================================================

-- Comprobación antes de borrar: cuánto se va a perder exactamente
SELECT 'customers_raw'         AS table_name, COUNT(*) AS rows FROM bank_churn.customers_raw
UNION ALL
SELECT 'customers',                 COUNT(*) FROM bank_churn.customers
UNION ALL
SELECT 'customer_predictions',      COUNT(*) FROM bank_churn.customer_predictions
UNION ALL
SELECT 'model_runs',                COUNT(*) FROM bank_churn.model_runs;

-- -----------------------------------------------------------------------------
-- Descomentar para ejecutar. CASCADE resuelve solo el orden de las claves
-- foráneas, así que no hace falta borrar las tablas una por una.
-- -----------------------------------------------------------------------------
-- DROP SCHEMA IF EXISTS bank_churn CASCADE;

-- -----------------------------------------------------------------------------
-- Reinicios parciales. Casi siempre bastan, y son mucho menos destructivos
-- -----------------------------------------------------------------------------

-- Recargar solo los datos de origen (conserva el esquema y las tablas modeladas):
--   TRUNCATE TABLE bank_churn.customers_raw;

-- Descartar las predicciones y las ejecuciones de puntuación, conservando los clientes:
--   TRUNCATE TABLE bank_churn.customer_predictions;
--   TRUNCATE TABLE bank_churn.model_runs RESTART IDENTITY CASCADE;

-- Reconstruir el registro operacional desde la tabla de aterrizaje:
--   TRUNCATE TABLE bank_churn.customers CASCADE;
--   -- y después volver a ejecutar la celda A5 del notebook 01

-- =============================================================================
-- Lado Delta. Esto se ejecuta en un notebook de Databricks, no aquí:
--
--   spark.sql("DROP TABLE IF EXISTS bank_churn.bronze.bank_customers_raw")
--   spark.sql("DROP SCHEMA IF EXISTS bank_churn.bronze CASCADE")
--   spark.sql("DROP SCHEMA IF EXISTS bank_churn.silver CASCADE")
--   spark.sql("DROP SCHEMA IF EXISTS bank_churn.gold   CASCADE")
--
-- O eliminar el catálogo analítico entero en una sola línea:
--   spark.sql("DROP CATALOG IF EXISTS bank_churn CASCADE")
--
-- Aviso: Delta conserva el historial. Una tabla gestionada que se elimina se
-- pierde, pero una que solo se ha sobrescrito se puede recuperar viajando en
-- el tiempo a una versión anterior:
--   SELECT * FROM bank_churn.bronze.bank_customers_raw VERSION AS OF 3
-- =============================================================================
