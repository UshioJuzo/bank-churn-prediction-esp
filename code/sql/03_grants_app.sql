-- =============================================================================
-- Predicción de abandono bancario - Permisos para la aplicación de Databricks
--
-- Esto se ejecuta en el editor SQL de DATABRICKS (Unity Catalog), NO en el
-- editor SQL de Lakebase. Son dos motores distintos.
--
-- Una aplicación de Databricks corre como su propio principal de servicio y NO
-- hereda los permisos de quien la creó. Sin estas concesiones la aplicación se
-- despliega bien y falla al consultar, con un error de permisos.
-- =============================================================================

-- Principal de servicio de la aplicación.
-- El identificador se copia de Apps > <aplicación> > Settings, donde aparece como
-- client id, y se sustituye en las cuatro concesiones de abajo antes de ejecutar.
--   <id-del-principal-de-servicio>

GRANT USE CATALOG ON CATALOG bank_churn
    TO `<id-del-principal-de-servicio>`;

GRANT USE SCHEMA ON SCHEMA bank_churn.gold
    TO `<id-del-principal-de-servicio>`;

-- Conceder SELECT sobre el esquema entero cubre también las tablas futuras, así
-- que añadir mañana una tabla a Gold no obliga a volver a conceder permisos.
GRANT SELECT ON SCHEMA bank_churn.gold
    TO `<id-del-principal-de-servicio>`;

-- -----------------------------------------------------------------------------
-- El modelo registrado
-- -----------------------------------------------------------------------------
-- Los experimentos de MLflow tienen sus propias listas de control de acceso,
-- separadas de las del catálogo. Una aplicación que carga un modelo por
-- runs:/<run_id> recibe "Run not found", un mensaje que engaña: lo que de
-- verdad significa es "no tienes permiso sobre el experimento".
--
-- Registrar el modelo en Unity Catalog lo mete bajo el mismo sistema de
-- permisos que las tablas. Se concede EXECUTE para que la aplicación pueda
-- cargarlo.

-- Aviso de sintaxis: en esta versión de Unity Catalog los modelos registrados
-- se tratan como funciones, así que se escribe ON FUNCTION, no ON MODEL.
GRANT EXECUTE ON FUNCTION bank_churn.gold.churn_model
    TO `<id-del-principal-de-servicio>`;

-- -----------------------------------------------------------------------------
-- Lo que a propósito NO se concede
-- -----------------------------------------------------------------------------
-- Ningún acceso a bronze ni a silver: la aplicación no tiene nada que hacer con
-- datos crudos ni intermedios. Es el principio de mínimo privilegio. Si algún
-- día la aplicación se ve comprometida, el alcance del daño es una tabla de
-- predicciones que ya estaba en el CRM.

-- -----------------------------------------------------------------------------
-- Verificación
-- -----------------------------------------------------------------------------
SHOW GRANTS `<id-del-principal-de-servicio>` ON SCHEMA bank_churn.gold;

-- Se espera ver USE SCHEMA y SELECT. Nada sobre bronze ni sobre silver.
