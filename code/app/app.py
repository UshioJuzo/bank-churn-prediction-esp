"""
Predicción de abandono de clientes bancarios - aplicación de retención.

Lee exclusivamente de tablas Gold en Unity Catalog, a través de un SQL Warehouse.
La predicción individual usa el mismo modelo registrado que produjo las tablas,
cargado desde MLflow por run_id.
"""

import os
from datetime import datetime, timezone

import mlflow
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from databricks import sql as dbsql
from databricks.sdk.core import Config

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
CATALOG      = os.getenv("CATALOG", "bank_churn")
GOLD         = os.getenv("GOLD_SCHEMA", "gold")
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID")
CAPACIDAD    = int(os.getenv("CAPACIDAD", "800"))

G = f"{CATALOG}.{GOLD}"

CHURN, SAFE, ACC, GREY = "#a8471f", "#2c5a72", "#8a5a08", "#78736a"
COLOR_RIESGO = {"alto": CHURN, "medio": ACC, "bajo": SAFE}

st.set_page_config(page_title="Retención de clientes | Predicción de abandono",
                   page_icon="●", layout="wide")


# ---------------------------------------------------------------------------
# Acceso a datos
# ---------------------------------------------------------------------------
@st.cache_resource
def _conexion():
    """Conexión al SQL Warehouse con la identidad de la aplicación."""
    if not WAREHOUSE_ID:
        raise RuntimeError(
            "Falta DATABRICKS_WAREHOUSE_ID. Añade el recurso SQL Warehouse en los "
            "ajustes de la app con la clave 'sql-warehouse'."
        )
    cfg = Config()
    return dbsql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )


@st.cache_data(ttl=600, show_spinner=False)
def consultar(sql: str) -> pd.DataFrame:
    """Ejecuta una consulta y devuelve un DataFrame. Cachea 10 minutos."""
    with _conexion().cursor() as cur:
        cur.execute(sql)
        return cur.fetchall_arrow().to_pandas()


@st.cache_resource(show_spinner="Cargando el modelo registrado...")
def cargar_modelo():
    """Carga el modelo de producción.

    Prioriza Unity Catalog: los experimentos de MLflow tienen permisos propios y
    el service principal de la app no suele estar en ellos, con lo que cargar por
    runs:/ falla con un engañoso 'Run not found'. El registro en UC queda bajo el
    mismo sistema de permisos que las tablas.
    """
    ref = consultar(f"SELECT * FROM {G}.modelo_produccion LIMIT 1").iloc[0]

    uc_model   = ref["uc_model"]   if "uc_model"   in ref.index else None
    uc_version = ref["uc_version"] if "uc_version" in ref.index else None

    if uc_model and uc_version:
        mlflow.set_registry_uri("databricks-uc")
        return mlflow.sklearn.load_model(f"models:/{uc_model}/{uc_version}"), ref

    if ref.get("run_id"):
        return mlflow.sklearn.load_model(f"runs:/{ref['run_id']}/modelo"), ref

    raise RuntimeError(
        "modelo_produccion no tiene ni uc_model ni run_id. Ejecuta la sección E ter "
        "del notebook 06 para registrar el modelo en Unity Catalog."
    )


def val(fila, *nombres, defecto=None):
    """Primer valor presente entre varios nombres posibles de columna.

    model_metrics cambió de esquema entre la version de análisis y la de
    producción: 'umbral_elegido' pasó a llamarse 'umbral'. La app no debería
    romperse por eso.
    """
    for n in nombres:
        if n in fila.index and pd.notna(fila[n]):
            return fila[n]
    if defecto is not None:
        return defecto
    raise KeyError(f"Ninguna de estas columnas existe en model_metrics: {nombres}")


def aviso_error(e: Exception, contexto: str):
    """Mensaje de error útil en lugar de un stack trace."""
    st.error(f"**No se pudo {contexto}.**\n\n`{type(e).__name__}: {e}`")
    with st.expander("Posibles causas"):
        st.markdown(
            "- El **service principal** de la app no tiene permisos sobre "
            f"`{CATALOG}`. Ejecuta `sql/03_grants_app.sql`.\n"
            "- El recurso **SQL Warehouse** no está añadido, o su clave no es "
            "`sql-warehouse`.\n"
            "- El warehouse está detenido: tarda unos segundos en arrancar.\n"
            "- Las tablas Gold no existen todavia: ejecuta el notebook 06."
        )


# ---------------------------------------------------------------------------
# Secciones
# ---------------------------------------------------------------------------
def resumen_ejecutivo():
    st.header("Resumen ejecutivo")

    met = consultar(f"SELECT * FROM {G}.model_metrics LIMIT 1").iloc[0]
    kpi = consultar(f"""
        SELECT COUNT(*)                                        AS clientes,
               AVG(CASE WHEN exited_real THEN 1.0 ELSE 0.0 END) AS tasa_real,
               SUM(CASE WHEN risk_level = 'alto' THEN 1 ELSE 0 END) AS alto_riesgo
        FROM   {G}.customer_churn_predictions
    """).iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes analizados", f"{int(kpi.clientes):,}".replace(",", "."))
    c2.metric("Tasa real de abandono", f"{kpi.tasa_real:.1%}")
    c3.metric("Clientes de alto riesgo", f"{int(kpi.alto_riesgo):,}".replace(",", "."),
              help=f"Cupo de la campaña: {CAPACIDAD} contactos")
    c4.metric("ROC-AUC del modelo", f"{met.roc_auc:.4f}",
              help=f"F1 = {met.f1:.4f} | Precisión = {met.precision:.4f}")

    st.divider()

    izq, der = st.columns([3, 2])
    with izq:
        st.subheader("Como se reparte la cartera")
        dist = consultar(f"""
            SELECT risk_level,
                   COUNT(*)                AS clientes,
                   AVG(churn_probability)  AS prob_media,
                   AVG(CASE WHEN exited_real THEN 1.0 ELSE 0.0 END) AS abandono_real
            FROM   {G}.customer_churn_predictions
            GROUP  BY risk_level
        """)
        orden = ["alto", "medio", "bajo"]
        dist["risk_level"] = pd.Categorical(dist.risk_level, orden, ordered=True)
        dist = dist.sort_values("risk_level")

        fig = px.bar(dist, x="risk_level", y="clientes", color="risk_level",
                     color_discrete_map=COLOR_RIESGO, text="clientes",
                     labels={"risk_level": "Nivel de riesgo", "clientes": "Clientes"})
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, height=330, margin=dict(t=20, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with der:
        st.subheader("Validación del modelo")
        dist["abandono_real"] = (dist.abandono_real * 100).round(1)
        dist["prob_media"] = (dist.prob_media * 100).round(1)
        st.dataframe(
            dist.rename(columns={"risk_level": "Nivel", "clientes": "Clientes",
                                 "prob_media": "Prob. media (%)",
                                 "abandono_real": "Abandono real (%)"}),
            hide_index=True, use_container_width=True)
        st.caption(
            "La probabilidad media y el abandono real coinciden en cada nivel: el modelo "
            "esta **calibrado**. Sin calibrar, la primera columna sobreestimaría la segunda."
        )


def segmentacion():
    st.header("Segmentación")
    st.caption("Los filtros afectan a los tres gráficos y al recuento superior.")

    datos = consultar(f"SELECT * FROM {G}.customer_churn_predictions")

    f1, f2, f3 = st.columns(3)
    paises = f1.multiselect("País", sorted(datos.geography.unique()),
                            default=sorted(datos.geography.unique()))
    tramos = f2.multiselect("Tramo de edad", ["18-29", "30-39", "40-49", "50-59", "60+"],
                            default=["18-29", "30-39", "40-49", "50-59", "60+"])
    actividad = f3.radio("Actividad", ["Todos", "Solo activos", "Solo inactivos"],
                         horizontal=True)

    d = datos[datos.geography.isin(paises) & datos.age_group.isin(tramos)]
    if actividad == "Solo activos":
        d = d[d.is_active_member]
    elif actividad == "Solo inactivos":
        d = d[~d.is_active_member]

    if d.empty:
        st.warning("Ningún cliente cumple los filtros seleccionados.")
        return

    a, b, c = st.columns(3)
    a.metric("Clientes filtrados", f"{len(d):,}".replace(",", "."))
    b.metric("Tasa de abandono", f"{d.exited_real.mean():.1%}")
    c.metric("De alto riesgo", f"{(d.risk_level == 'alto').sum():,}".replace(",", "."))

    st.divider()
    g1, g2 = st.columns(2)

    with g1:
        t = (d.groupby("age_group")["exited_real"].mean().reindex(
             ["18-29", "30-39", "40-49", "50-59", "60+"]).dropna() * 100).round(1)
        fig = px.bar(x=t.index, y=t.values, text=t.values,
                     labels={"x": "Tramo de edad", "y": "% abandono"},
                     title="Abandono por edad")
        fig.update_traces(marker_color=CHURN, textposition="outside")
        fig.update_layout(height=330, margin=dict(t=45, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        t = (d.groupby("geography")["exited_real"].mean() * 100).round(1).sort_values()
        fig = px.bar(x=t.values, y=t.index, orientation="h", text=t.values,
                     labels={"x": "% abandono", "y": "País"},
                     title="Abandono por país")
        fig.update_traces(marker_color=CHURN, textposition="outside")
        fig.update_layout(height=330, margin=dict(t=45, b=10))
        st.plotly_chart(fig, use_container_width=True)

    piv = (d.assign(act=np.where(d.is_active_member, "Activo", "Inactivo"))
             .groupby(["age_group", "act"])["exited_real"].mean()
             .mul(100).round(1).reset_index())
    piv["age_group"] = pd.Categorical(
        piv.age_group, ["18-29", "30-39", "40-49", "50-59", "60+"], ordered=True)
    piv = piv.sort_values("age_group").dropna(subset=["age_group"])

    fig = px.bar(piv, x="age_group", y="exited_real", color="act",
                 barmode="group", text_auto=".1f",
                 color_discrete_map={"Activo": SAFE, "Inactivo": CHURN},
                 labels={"age_group": "Tramo de edad", "exited_real": "% abandono",
                         "act": ""},
                 title="Abandono por edad y actividad")
    fig.update_traces(textposition="outside")
    fig.update_layout(height=400, margin=dict(t=50, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0,
                                  xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "El hallazgo principal del análisis: entre los **inactivos** el riesgo crece con la "
        "edad hasta superar el 85%, mientras que entre los activos vuelve a bajar después de "
        "los 60. La actividad es la única variable sobre la que el banco puede intervenir."
    )


def riesgo_clientes():
    st.header("Clientes en riesgo")
    st.caption("Lista priorizada para la campaña de retención. No se muestran apellidos.")

    f1, f2, f3 = st.columns([1, 1, 2])
    nivel = f1.selectbox("Nivel de riesgo", ["alto", "medio", "bajo", "todos"])
    n = f2.number_input("Filas a mostrar", 10, 2000, 100, step=10)
    pais = f3.multiselect("País", ["France", "Germany", "Spain"],
                          default=["France", "Germany", "Spain"])

    donde = [f"geography IN ({','.join(chr(39) + p + chr(39) for p in pais)})"] if pais else ["1=1"]
    if nivel != "todos":
        donde.append(f"risk_level = '{nivel}'")

    tabla = consultar(f"""
        SELECT customer_id, ROUND(churn_probability, 4) AS probabilidad,
               risk_level AS nivel, accion_sugerida AS accion,
               geography AS pais, age_group AS edad,
               is_active_member AS activo, products_group AS productos
        FROM   {G}.customer_churn_predictions
        WHERE  {' AND '.join(donde)}
        ORDER  BY churn_probability DESC
        LIMIT  {int(n)}
    """)

    if tabla.empty:
        st.warning("Ningún cliente cumple los filtros seleccionados.")
        return

    st.dataframe(
        tabla, hide_index=True, use_container_width=True, height=460,
        column_config={
            "probabilidad": st.column_config.ProgressColumn(
                "Probabilidad", min_value=0.0, max_value=1.0, format="%.3f"),
            "customer_id": st.column_config.NumberColumn("Cliente", format="%d"),
        })

    st.download_button(
        "Descargar como CSV", tabla.to_csv(index=False).encode("utf-8"),
        f"clientes_riesgo_{nivel}.csv", "text/csv")

    if nivel == "alto":
        st.info(
            f"**{len(tabla)} clientes mostrados de un cupo de campaña de {CAPACIDAD}.** "
            "El cupo se reparte por país para que un cliente en riesgo tenga la misma "
            "probabilidad de ser contactado viva donde viva."
        )


def desempeno():
    st.header("Desempeño del modelo")

    met = consultar(f"SELECT * FROM {G}.model_metrics LIMIT 1").iloc[0]

    st.subheader("Comparación de modelos")
    try:
        comp = consultar(f"SELECT * FROM {G}.model_comparison")
        comp = comp.sort_values("average_precision", ascending=True)
        fig = px.bar(comp, x="average_precision", y="modelo", orientation="h",
                     color="es_linea_base", text_auto=".4f",
                     color_discrete_map={True: GREY, False: CHURN},
                     labels={"average_precision": "Average precision (validación cruzada)",
                             "modelo": "", "es_linea_base": "Linea base"})
        fig.update_traces(textposition="inside", insidetextanchor="end")
        fig.update_layout(height=380, margin=dict(t=20, b=10),
                          xaxis=dict(range=[0, 1]))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "En gris las líneas base. `baseline_negocio` es una regla de dos variables "
            "que el banco podría aplicar sin ningún modelo: es el rival real."
        )
    except Exception:
        st.info("Comparación de modelos no disponible. Ejecuta el notebook 06.")

    st.divider()
    izq, der = st.columns(2)

    with izq:
        st.subheader("Matriz de confusion")
        cm = [[int(met.TN), int(met.FP)], [int(met.FN), int(met.TP)]]
        fig = go.Figure(go.Heatmap(
            z=cm, x=["Predice: se queda", "Predice: abandona"],
            y=["Real: se queda", "Real: abandona"],
            colorscale="Oranges", showscale=False,
            text=[[f"TN<br>{cm[0][0]:,}", f"FP<br>{cm[0][1]:,}"],
                  [f"FN<br>{cm[1][0]:,}", f"TP<br>{cm[1][1]:,}"]],
            texttemplate="%{text}", textfont={"size": 15}))
        # Plotly dibuja el eje Y de abajo arriba: sin esto la matriz sale invertida
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=340, margin=dict(t=20, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Sobre el conjunto de prueba, al umbral "
            f"{float(val(met, 'umbral', 'umbral_elegido')):.3f}. "
            "Los falsos negativos son el error caro: clientes que se van sin que nadie lo intente."
        )

    with der:
        st.subheader("Variables mas influyentes")
        try:
            imp = consultar(f"SELECT * FROM {G}.feature_importance ORDER BY importancia")
            fig = px.bar(imp, x="importancia", y="variable", orientation="h",
                         error_x="std", color="distinguible_de_cero",
                         color_discrete_map={True: CHURN, False: GREY},
                         labels={"importancia": "Caida de average precision al permutar",
                                 "variable": "", "distinguible_de_cero": "Efecto real"})
            fig.update_layout(height=340, margin=dict(t=20, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Importancia por permutacion sobre datos no vistos. En gris, las variables "
                "cuyo efecto no se distingue de cero."
            )
        except Exception:
            st.info("Importancia de variables no disponible. Ejecuta el notebook 06.")

    st.divider()
    st.subheader("Ficha técnica")
    a, b, c, d = st.columns(4)
    a.metric("ROC-AUC", f"{met.roc_auc:.4f}")
    b.metric("Average precision", f"{met.average_precision:.4f}")
    c.metric("Brier score", f"{float(val(met, 'brier')):.4f}",
             help="Calidad de la calibración. Menor es mejor.")
    d.metric("Precision", f"{met.precision:.4f}")

    st.markdown(
        f"""
- **Modelo:** {met.modelo} sin la variable `gender`, calibrado isotónicamente.
- **Por que sin genero:** su aporte medido fue de **0,12 puntos de recall (unos dos clientes)**.
  No justifica usar una característica protegida para repartir un beneficio.
- **Umbral:** {float(val(met, 'umbral', 'umbral_elegido')):.4f}, fijado por capacidad operativa y
  validado contra el umbral de rentabilidad economica ({float(val(met, 'umbral_coste')):.4f}).
- **Limite conocido:** el modelo detecta bien el abandono de clientes mayores e inactivos, y se
  le escapa el de los mas jovenes.
"""
    )


def prediccion_individual():
    st.header("Predicción individual")
    st.caption("Usa el mismo modelo registrado que genero las tablas de esta aplicación.")

    try:
        modelo, ref = cargar_modelo()
    except Exception as e:
        aviso_error(e, "cargar el modelo registrado")
        return

    origen = (f"Unity Catalog `{ref['uc_model']}` v{ref['uc_version']}"
              if ref.get("uc_model") else f"run `{str(ref.get('run_id', ''))[:12]}`")
    st.success(f"Modelo cargado: **{ref['familia']}** | {origen}")

    with st.form("prediccion"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Perfil**")
            geography = st.selectbox("País", ["France", "Germany", "Spain"])
            age       = st.number_input("Edad", 18, 100, 45)
            tenure    = st.number_input("Antigüedad (años)", 0, 10, 5)
        with c2:
            st.markdown("**Situación financiera**")
            credit_score     = st.number_input("Puntaje crediticio", 300, 900, 650)
            balance          = st.number_input("Saldo", 0.0, 300000.0, 0.0, step=1000.0)
            estimated_salary = st.number_input("Salario estimado", 0.0, 250000.0, 100000.0,
                                               step=1000.0)
        with c3:
            st.markdown("**Relacion con el banco**")
            num_of_products  = st.selectbox("Productos contratados", [1, 2, 3, 4])
            is_active_member = st.checkbox("Cliente activo", value=True)
            has_cr_card      = st.checkbox("Tiene tarjeta de crédito", value=True)

        enviado = st.form_submit_button("Calcular riesgo", type="primary")

    if not enviado:
        st.info(
            "El formulario **no pide el genero**: el modelo desplegado no lo utiliza. "
            "Su aporte medido era de unos dos clientes de 2.037, insuficiente para justificar "
            "el uso de una característica protegida."
        )
        return

    # Se construyen las 13 columnas que el pipeline vio al entrenar.
    # gender no se usa: el ColumnTransformer lo descarta.
    fila = pd.DataFrame([{
        "credit_score": credit_score, "geography": geography, "gender": "Female",
        "age": age, "tenure": tenure, "balance": float(balance),
        "num_of_products": num_of_products,
        "has_cr_card": int(has_cr_card), "is_active_member": int(is_active_member),
        "estimated_salary": float(estimated_salary),
        "balance_zero": int(balance == 0),
        "age_group": ("18-29" if age < 30 else "30-39" if age < 40 else
                      "40-49" if age < 50 else "50-59" if age < 60 else "60+"),
        "products_group": str(num_of_products) if num_of_products <= 2 else "3+",
    }])

    try:
        p = float(modelo.predict_proba(fila)[0, 1])
    except Exception as e:
        aviso_error(e, "calcular la predicción")
        return

    met = consultar(f"SELECT * FROM {G}.model_metrics LIMIT 1").iloc[0]
    umbral       = float(val(met, "umbral", "umbral_elegido"))
    umbral_coste = float(val(met, "umbral_coste", defecto=0.194444))
    nivel = "alto" if p >= umbral else "medio" if p >= umbral_coste else "bajo"

    st.divider()
    a, b, c = st.columns(3)
    a.metric("Probabilidad de abandono", f"{p:.1%}")
    b.metric("Clasificacion", "Abandona" if p >= umbral else "Permanece")
    c.metric("Nivel de riesgo", nivel.upper())

    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=p * 100,
        number={"suffix": "%"},
        gauge={"axis": {"range": [0, 100]},
               "bar": {"color": COLOR_RIESGO[nivel]},
               "steps": [{"range": [0, umbral_coste * 100], "color": "#e8e2d5"},
                         {"range": [umbral_coste * 100, umbral * 100],
                          "color": "#f6ead2"},
                         {"range": [umbral * 100, 100], "color": "#f0e0d6"}],
               "threshold": {"line": {"color": CHURN, "width": 3},
                             "value": umbral * 100}}))
    fig.update_layout(height=260, margin=dict(t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

    if nivel == "alto":
        accion = ("Reactivación prioritaria: contacto telefónico con incentivo de uso"
                  if not is_active_member else
                  "Revisión de cartera: auditar la combinación de productos"
                  if num_of_products >= 3 else
                  "Fidelización: contacto comercial y revisión de condiciones")
        st.error(f"**Acción sugerida:** {accion}")
    elif nivel == "medio":
        st.warning("**Acción sugerida:** vigilancia. Incluir si queda presupuesto de campaña.")
    else:
        st.success("**Sin acción.** Riesgo por debajo del umbral de rentabilidad del contacto.")

    st.warning(
        "**Advertencia de uso.** Esta estimacion es una **probabilidad**, no un diagnostico, y "
        "esta entrenada sobre datos historicos de una cartera concreta. No debe usarse para "
        "denegar productos ni condiciones a un cliente. Su único proposito es **priorizar "
        "acciones de retención** con un presupuesto limitado. Las asociaciones detectadas no "
        "implican causalidad: que la inactividad se asocie al abandono no prueba que reactivar "
        "lo evite."
    )


# ---------------------------------------------------------------------------
# Navegación
# ---------------------------------------------------------------------------
SECCIONES = {
    "Resumen ejecutivo":    resumen_ejecutivo,
    "Segmentación":         segmentacion,
    "Clientes en riesgo":   riesgo_clientes,
    "Desempeño del modelo": desempeno,
    "Predicción individual": prediccion_individual,
}

with st.sidebar:
    st.title("Retención de clientes")
    st.caption("Predicción de abandono bancario")
    st.divider()
    eleccion = st.radio("Sección", list(SECCIONES), label_visibility="collapsed")
    st.divider()

    try:
        actualizado = consultar(
            f"SELECT MAX(scored_at) AS t FROM {G}.customer_churn_predictions").iloc[0].t
        st.caption(f"**Fuente:** `{G}`")
        st.caption(f"**Datos actualizados:** {pd.to_datetime(actualizado):%d/%m/%Y %H:%M} UTC")
    except Exception:
        st.caption(f"**Fuente:** `{G}`")
        st.caption("Fecha de actualización no disponible")

    st.caption(f"**Consultado:** {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC")
    if st.button("Refrescar datos y modelo", use_container_width=True):
        # cache_resource guarda el modelo y la conexión: sin limpiarlo, la app
        # seguiría sirviendo el objeto de la sesión anterior aunque las tablas
        # hayan cambiado.
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

st.title("Predicción de abandono de clientes bancarios")

try:
    SECCIONES[eleccion]()
except Exception as e:
    aviso_error(e, f"cargar la sección '{eleccion}'")
