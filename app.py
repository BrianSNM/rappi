"""
Rappi Insights
Streamlit con 4 pestañas:
1. Mapa geoespacial (Prueba 1)
2. Análisis estadístico + IA (Prueba 1)
3. Operations Bot con LangGraph (Prueba 2 - 70%)
4. Reporte Ejecutivo de Insights (Prueba 2 - 30%)
"""
import json
import os
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import analytics as A
from interpreter import interpretar
from ops_bot import OperationsBot, SUGERENCIAS_RAPIDAS
from ops_insights import generate_executive_report

# ---------- CONFIG ----------
DATA_DIR = Path(__file__).parent / "data"
CLEAN_CSV = DATA_DIR / "clean.csv"
OPS_DATA_FILE = DATA_DIR / "master_data.parquet"

RAPPI_RED = "#FF2300"
RAPPI_CORAL = "#CE7B6D"
RAPPI_BROWN = "#9C4221"
BLACK = "#000000"
WHITE = "#FFFFFF"

st.set_page_config(
    page_title="Pira – Rappi Insights",
    page_icon="🛵",
    layout="wide",
)

st.markdown(
    f"""
    <style>
        .stApp {{ background-color: {BLACK}; color: {WHITE}; }}
        .block-container {{
            max-width: 100% !important;
            padding-left: 2rem; padding-right: 2rem;
        }}
        h1, h2, h3, h4 {{ color: {RAPPI_RED} !important; font-weight: 700; }}
        [data-testid="stMetric"] {{
            background: linear-gradient(135deg, {RAPPI_BROWN} 0%, {RAPPI_RED} 100%);
            padding: 16px; border-radius: 12px;
        }}
        [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{
            color: {WHITE} !important;
        }}
        .stSelectbox label, .stMultiSelect label {{
            color: {RAPPI_CORAL} !important; font-weight: 600;
        }}
        .stTabs [data-baseweb="tab-list"] {{
            gap: 8px; border-bottom: 2px solid {RAPPI_BROWN};
        }}
        .stTabs [data-baseweb="tab"] {{
            background-color: #1a1a1a; color: {WHITE};
            border-radius: 8px 8px 0 0; padding: 10px 22px; font-weight: 600;
        }}
        .stTabs [aria-selected="true"] {{
            background-color: {RAPPI_RED} !important; color: {WHITE} !important;
        }}
        .pira-header {{
            background: linear-gradient(90deg, {RAPPI_RED} 0%, {RAPPI_BROWN} 100%);
            padding: 18px 24px; border-radius: 12px; margin-bottom: 18px;
        }}
        .pira-header h1 {{ color: {WHITE} !important; margin: 0; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="pira-header">
        <h1>🛵 Rappi Insights</h1>
    </div>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_data() -> pd.DataFrame:
    if not CLEAN_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(CLEAN_CSV)


@st.cache_data
def load_ops_data() -> pd.DataFrame:
    if not OPS_DATA_FILE.exists():
        return pd.DataFrame()
    return pd.read_parquet(OPS_DATA_FILE)


@st.cache_resource
def get_ops_bot():
    df_ops = load_ops_data()
    if df_ops.empty:
        return None
    return OperationsBot(df_ops)


@st.cache_data
def get_executive_report(_df_ops_signature: int):
    df_ops = load_ops_data()
    if df_ops.empty:
        return None
    return generate_executive_report(df_ops)


# Cliente Gemini directo (para el chat de oportunidades)
def chat_gemini(messages: list[dict], modelo: str = "gemini-flash-latest") -> str:
    """
    Llama a Gemini con un historial de chat. Devuelve texto plano.
    messages: lista de dicts con 'role' (user/assistant/system) y 'content'.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return "⚠ No hay GEMINI_API_KEY/GOOGLE_API_KEY en el entorno."
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        # Separar system del resto
        system_instruction = None
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_instruction = m["content"]
            else:
                # Gemini usa 'user' y 'model'
                role = "user" if m["role"] == "user" else "model"
                chat_msgs.append({"role": role, "parts": [m["content"]]})

        model = genai.GenerativeModel(
            model_name=modelo,
            system_instruction=system_instruction,
        )
        # El último mensaje es el prompt; los anteriores son history
        if not chat_msgs:
            return "(sin mensajes)"
        history = chat_msgs[:-1]
        last_user_msg = chat_msgs[-1]["parts"][0]
        chat = model.start_chat(history=history)
        resp = chat.send_message(last_user_msg)
        # Normalizar respuesta (puede venir str o lista)
        text = getattr(resp, "text", None)
        if text:
            return text
        return str(resp)
    except Exception as e:
        return f"⚠ Error Gemini: {type(e).__name__}: {e}"


df = load_data()
if df.empty:
    st.error(f"No existe {CLEAN_CSV}")
    st.stop()


# =====================================================================
# FILTROS (tabs Mapa y Análisis)
# =====================================================================
FILTER_COLS = [
    ("platform", "Plataforma"),
    ("city", "Ciudad"),
    ("zone_id", "Zona"),
    ("tier", "Tier"),
    ("merchant", "Comercio"),
    ("product_id", "Producto"),
]

for col, _ in FILTER_COLS:
    if col in df.columns:
        state_key = f"filt_{col}"
        if state_key not in st.session_state:
            st.session_state[state_key] = {
                v: True for v in sorted(df[col].dropna().unique())
            }


def render_filter(col: str, label: str):
    if col not in df.columns:
        return
    state_key = f"filt_{col}"
    estado = st.session_state[state_key]
    n_sel = sum(estado.values())
    n_tot = len(estado)
    with st.expander(f"**{label}** · {n_sel}/{n_tot}", expanded=False):
        b1, b2 = st.columns(2)
        if b1.button("Todos", key=f"all_{col}", use_container_width=True):
            for k in estado:
                estado[k] = True
            st.rerun()
        if b2.button("Ninguno", key=f"none_{col}", use_container_width=True):
            for k in estado:
                estado[k] = False
            st.rerun()
        for valor in estado.keys():
            estado[valor] = st.checkbox(
                str(valor),
                value=estado[valor],
                key=f"chk_{col}_{valor}",
            )


with st.popover("🎛  Filtros (Mapa y Análisis)", use_container_width=True):
    cols = st.columns(3)
    for i, (col, label) in enumerate(FILTER_COLS):
        with cols[i % 3]:
            render_filter(col, label)

mask = pd.Series(True, index=df.index)
for col, _ in FILTER_COLS:
    if col in df.columns:
        seleccionados = [
            v for v, activo in st.session_state[f"filt_{col}"].items() if activo
        ]
        mask &= df[col].isin(seleccionados)

df_f = df[mask].copy()

if df_f.empty:
    st.warning("Sin datos con los filtros seleccionados.")
    st.stop()

df_f = A.add_valor_total(df_f)


# =====================================================================
# TABS
# =====================================================================
tab_mapa, tab_analisis, tab_bot, tab_reporte = st.tabs([
    "🗺️  Mapa",
    "📊  Análisis Estadístico",
    "🤖  Operations Bot",
    "📋  Reporte Ejecutivo",
])


# =====================================================================
# TAB 1 — MAPA
# =====================================================================
with tab_mapa:
    df_geo = df_f.dropna(subset=["lat", "lon"])
    if df_geo.empty:
        st.warning("No hay direcciones con coordenadas en este filtro.")
    else:
        def _fmt(v):
            return "—" if pd.isna(v) else f"${v:.2f}"

        def build_tooltip(sub: pd.DataFrame, address: str) -> str:
            rows_html = []
            for _, r in sub.iterrows():
                rows_html.append(
                    "<tr style='border-bottom:1px solid #2a2a2a;'>"
                    f"<td style='padding:3px 6px; color:{RAPPI_RED}; font-weight:700;'>"
                    f"{r['platform']}</td>"
                    f"<td style='padding:3px 6px;'>{r['merchant']}</td>"
                    f"<td style='padding:3px 6px;'>{r['product_id']}</td>"
                    f"<td style='padding:3px 6px; text-align:right;'>{_fmt(r['subtotal'])}</td>"
                    f"<td style='padding:3px 6px; text-align:right;'>{_fmt(r['delivery_fee'])}</td>"
                    f"<td style='padding:3px 6px; text-align:right;'>{_fmt(r['service_fee'])}</td>"
                    "</tr>"
                )
            return (
                f"<div style='font-family:sans-serif; max-width:480px;'>"
                f"<div style='color:{RAPPI_RED}; font-weight:700; font-size:13px;"
                f" margin-bottom:4px;'>📍 {address}</div>"
                f"<div style='font-size:11px; color:{RAPPI_CORAL}; margin-bottom:6px;'>"
                f"{len(sub)} registros · {sub['platform'].nunique()} plataformas</div>"
                "<table style='border-collapse:collapse; font-size:11px; width:100%;'>"
                f"<thead><tr style='background:{RAPPI_BROWN}; color:{WHITE};'>"
                "<th style='padding:4px 6px; text-align:left;'>Plataforma</th>"
                "<th style='padding:4px 6px; text-align:left;'>Comercio</th>"
                "<th style='padding:4px 6px; text-align:left;'>Producto</th>"
                "<th style='padding:4px 6px; text-align:right;'>Subtotal</th>"
                "<th style='padding:4px 6px; text-align:right;'>Delivery</th>"
                "<th style='padding:4px 6px; text-align:right;'>Service</th>"
                f"</tr></thead><tbody>{''.join(rows_html)}</tbody></table></div>"
            )

        grouped = []
        for (lat, lon), sub in df_geo.groupby(["lat", "lon"], sort=False):
            grouped.append({
                "lat": float(lat),
                "lon": float(lon),
                "address": sub.iloc[0]["address"],
                "n": len(sub),
                "tooltip_html": build_tooltip(sub, sub.iloc[0]["address"]),
            })
        df_map = pd.DataFrame(grouped)

        layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_map,
            get_position=["lon", "lat"],
            get_fill_color=[255, 35, 0, 200],
            get_line_color=[255, 255, 255, 255],
            line_width_min_pixels=2,
            get_radius=300,
            radius_min_pixels=10,
            radius_max_pixels=28,
            pickable=True,
            auto_highlight=True,
        )

        lat_c = (df_map["lat"].min() + df_map["lat"].max()) / 2
        lon_c = (df_map["lon"].min() + df_map["lon"].max()) / 2
        span = max(
            df_map["lat"].max() - df_map["lat"].min(),
            df_map["lon"].max() - df_map["lon"].min(),
            0.01,
        )
        if span < 0.05:    zoom = 13
        elif span < 0.5:   zoom = 11
        elif span < 2:     zoom = 9
        elif span < 8:     zoom = 6
        else:              zoom = 4

        view_state = pdk.ViewState(
            latitude=float(lat_c),
            longitude=float(lon_c),
            zoom=zoom,
            pitch=0,
        )

        tooltip = {
            "html": "{tooltip_html}",
            "style": {
                "backgroundColor": BLACK,
                "color": WHITE,
                "border": f"2px solid {RAPPI_RED}",
                "borderRadius": "10px",
                "padding": "10px",
                "boxShadow": "0 4px 14px rgba(0,0,0,0.5)",
            },
        }

        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip=tooltip,
            map_style="dark",
        )

        col_map, col_kpis = st.columns([3, 1], gap="medium")

        with col_map:
            st.pydeck_chart(deck, use_container_width=True, height=720)

        with col_kpis:
            st.metric("Registros", f"{len(df_f):,}")
            st.metric("Direcciones", df_f["address"].nunique())
            st.metric("Subtotal prom.", f"${df_f['subtotal'].mean():.2f}")
            st.metric("Delivery prom.", f"${df_f['delivery_fee'].mean():.2f}")
            st.metric("Service prom.", f"${df_f['service_fee'].mean():.2f}")
            st.metric("Valor total prom.", f"${df_f['valor_total'].mean():.2f}")

        with st.expander("Ver datos en tabla"):
            st.dataframe(df_f, use_container_width=True, hide_index=True)


# =====================================================================
# TAB 2 — ANÁLISIS ESTADÍSTICO + IA
# =====================================================================
with tab_analisis:
    st.markdown("### Análisis competitivo automatizado")
    st.caption(
        "Cálculos estadísticos sobre la muestra filtrada. "
        "Se actualizan automáticamente con los filtros."
    )

    kpis = A.kpis_globales(df_f)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Subtotal prom.", f"${kpis['subtotal_avg']:.2f}")
    c2.metric("Delivery prom.", f"${kpis['delivery_avg']:.2f}")
    c3.metric("Service prom.", f"${kpis['service_avg']:.2f}")
    c4.metric("Valor total prom.", f"${kpis['valor_total_avg']:.2f}")

    st.markdown("---")

    st.markdown("#### 1. Distribución por plataforma")
    metric_sel = st.radio(
        "Métrica",
        ["subtotal", "delivery_fee", "service_fee", "valor_total"],
        horizontal=True,
        key="metric_dist",
    )
    dist = A.distribucion_por_plataforma(df_f, metric_sel)
    if not dist.empty:
        st.dataframe(dist, hide_index=True, use_container_width=True)
    else:
        st.info("Sin datos para esta métrica.")

    st.markdown("#### 2. Comparativa pareada (misma dirección + producto)")
    st.caption(
        "Delta de medias con IC bootstrap 95%, t-test pareado y Wilcoxon."
    )
    pareado = A.comparativa_pareada(df_f, metric_sel)
    if not pareado.empty:
        st.dataframe(pareado, hide_index=True, use_container_width=True)
    else:
        st.info("No hay suficientes pares para comparar con esta métrica.")

    st.markdown("#### 3. Estructura de fees (% del valor total)")
    fees = A.estructura_de_fees(df_f)
    if not fees.empty:
        st.dataframe(fees, hide_index=True, use_container_width=True)

    st.markdown("#### 4. Consistencia de precios por producto")
    st.caption("CV alto = precio inconsistente entre direcciones.")
    cons = A.consistencia_precios(df_f)
    if not cons.empty:
        st.dataframe(cons, hide_index=True, use_container_width=True)

    st.markdown("#### 5. Cobertura competitiva")
    cob = A.cobertura_competitiva(df_f)
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Por ciudad**")
        if not cob["por_ciudad"].empty:
            st.dataframe(cob["por_ciudad"], use_container_width=True)
    with cc2:
        st.markdown("**Por tier**")
        if not cob["por_tier"].empty:
            st.dataframe(cob["por_tier"], use_container_width=True)

    st.markdown("---")
    st.markdown("### 🤖 Interpretación automatizada")
    st.caption(
        "Análisis generado por IA sobre los estadísticos arriba, "
        "considerando el contexto de Pricing / Operations / Strategy."
    )

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        if st.button("Generar interpretación", type="primary"):
            with st.spinner("Analizando con Gemini..."):
                resumen = A.resumen_para_ia(df_f)
                interpretacion = interpretar(resumen)
            st.session_state["last_interpretation"] = interpretacion
    with col_info:
        st.caption(
            "💡 Cambia los filtros y vuelve a generar para una "
            "interpretación contextualizada."
        )

    if "last_interpretation" in st.session_state:
        st.markdown(st.session_state["last_interpretation"])


# =====================================================================
# TAB 3 — OPERATIONS BOT
# =====================================================================
with tab_bot:
    st.markdown("### Operations Intelligence Bot")
    st.caption(
        "Pregúntale al bot sobre métricas operacionales por zona, país o tendencia. "
        "Mantiene memoria de la conversación."
    )

    df_ops = load_ops_data()
    if df_ops.empty:
        st.error(
            f"No existe `{OPS_DATA_FILE}`. "
            "Ejecuta `python processor.py` para generarlo."
        )
    else:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Países", df_ops["COUNTRY"].nunique())
        col_b.metric("Zonas", df_ops["ZONE"].nunique())
        col_c.metric("Métricas", df_ops["METRIC"].nunique())

        if "bot_messages" not in st.session_state:
            st.session_state.bot_messages = []

        st.markdown("**💡 Preguntas sugeridas:**")
        sug_cols = st.columns(len(SUGERENCIAS_RAPIDAS))
        pregunta_sugerida = None
        for i, sug in enumerate(SUGERENCIAS_RAPIDAS):
            label = sug[:38] + "..." if len(sug) > 38 else sug
            if sug_cols[i].button(
                label,
                key=f"sug_{i}",
                use_container_width=True,
                help=sug,
            ):
                pregunta_sugerida = sug

        if st.session_state.bot_messages:
            if st.button("🧹 Nueva conversación"):
                st.session_state.bot_messages = []
                st.rerun()

        st.markdown("---")

        for msg in st.session_state.bot_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("codigo"):
                    with st.expander("Ver código pandas generado"):
                        st.code(msg["codigo"], language="python")

        prompt = pregunta_sugerida or st.chat_input(
            "Ej: ¿Cuáles son las 5 zonas con mayor Lead Penetration?"
        )

        if prompt:
            st.session_state.bot_messages.append(
                {"role": "user", "content": prompt}
            )
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Analizando datos..."):
                    bot = get_ops_bot()
                    if bot is None:
                        respuesta = "Error: no se pudo cargar el bot."
                        codigo = ""
                    else:
                        resultado = bot.query(
                            prompt,
                            history=st.session_state.bot_messages[:-1],
                        )
                        respuesta = resultado["respuesta"]
                        codigo = resultado["codigo"]
                st.markdown(respuesta)
                if codigo:
                    with st.expander("Ver código pandas generado"):
                        st.code(codigo, language="python")

            st.session_state.bot_messages.append({
                "role": "assistant",
                "content": respuesta,
                "codigo": codigo,
            })

            if pregunta_sugerida:
                st.rerun()


# =====================================================================
# TAB 4 — REPORTE EJECUTIVO DE INSIGHTS
# =====================================================================
with tab_reporte:
    st.markdown("### Reporte Ejecutivo de Insights Operacionales")
    st.caption(
        "Análisis automático sobre `master_data.parquet` en 5 categorías: "
        "anomalías, tendencias, benchmarking, correlaciones y oportunidades."
    )

    df_ops = load_ops_data()
    if df_ops.empty:
        st.error(
            f"No existe `{OPS_DATA_FILE}`. "
            "Ejecuta `python processor.py` para generarlo."
        )
    else:
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Países", df_ops["COUNTRY"].nunique())
        col_b.metric("Zonas", df_ops["ZONE"].nunique())
        col_c.metric("Métricas", df_ops["METRIC"].nunique())
        col_d.metric("Filas analizadas", f"{len(df_ops):,}")

        st.markdown("---")

        col_btn, col_info = st.columns([1, 4])
        with col_btn:
            generar = st.button(
                "🚀 Generar reporte",
                type="primary",
                use_container_width=True,
            )
        with col_info:
            st.caption(
                "El reporte se calcula automáticamente sobre los 9 países "
                "y todas las zonas. Identifica deterioros, tendencias y oportunidades."
            )

        if generar or "exec_report" in st.session_state:
            if generar or "exec_report" not in st.session_state:
                with st.spinner("Calculando insights sobre toda la base..."):
                    report = get_executive_report(len(df_ops))
                st.session_state["exec_report"] = report
                st.session_state["exec_report_ts"] = datetime.now()

            report = st.session_state["exec_report"]
            ts = st.session_state["exec_report_ts"].strftime("%Y-%m-%d %H:%M")
            st.caption(f"Generado: {ts}")

            sub_tabs = st.tabs([
                "📋 Reporte completo",
                "🚨 Anomalías",
                "📉 Tendencias",
                "🔍 Benchmarking",
                "🔗 Correlaciones",
                "💡 Oportunidades",
            ])

            with sub_tabs[0]:
                st.markdown(report["markdown"])
                st.download_button(
                    "⬇ Descargar como Markdown",
                    data=report["markdown"],
                    file_name=f"reporte_rappi_{ts.replace(' ','_').replace(':','-')}.md",
                    mime="text/markdown",
                )

            with sub_tabs[1]:
                st.markdown("##### Cambios > 10% entre L1W y L0W")
                if report["anomalias"].empty:
                    st.info("Sin anomalías significativas.")
                else:
                    st.dataframe(
                        report["anomalias"],
                        use_container_width=True,
                        hide_index=True,
                    )

            # ---------------- TENDENCIAS ----------------
            with sub_tabs[2]:
                st.markdown("##### Métricas en deterioro 3+ semanas consecutivas")
                if report["tendencias"].empty:
                    st.info("Sin tendencias deteriorándose por 3+ semanas.")
                else:
                    st.dataframe(
                        report["tendencias"],
                        use_container_width=True,
                        hide_index=True,
                    )

                st.markdown("---")
                st.markdown("##### 📈 Explorador interactivo de tendencias")
                st.caption(
                    "Elige una métrica, un nivel de agregación y los elementos "
                    "específicos a comparar."
                )

                metricas_disp = sorted(df_ops["METRIC"].dropna().unique())
                metric_trend = st.selectbox(
                    "Métrica a graficar",
                    metricas_disp,
                    key="trend_metric",
                )

                nivel = st.radio(
                    "Nivel de agregación",
                    ["País", "Ciudad", "Zona"],
                    horizontal=True,
                    key="trend_nivel",
                    help=(
                        "País: promedia todas las zonas del país. "
                        "Ciudad: promedia todas las zonas de la ciudad. "
                        "Zona: una línea por zona individual."
                    ),
                )

                col_metric_data = df_ops[df_ops["METRIC"] == metric_trend].copy()

                if nivel == "País":
                    opciones = sorted(col_metric_data["COUNTRY"].dropna().unique())
                    default_sel = opciones[: min(5, len(opciones))]
                    seleccion = st.multiselect(
                        "Países a comparar",
                        opciones,
                        default=default_sel,
                        key="trend_paises",
                    )
                    df_plot_base = col_metric_data[col_metric_data["COUNTRY"].isin(seleccion)]
                    df_plot = (
                        df_plot_base.groupby(["COUNTRY", "WEEK_AGO"], as_index=False)["VALUE"]
                        .mean()
                        .rename(columns={"COUNTRY": "grupo"})
                    )

                elif nivel == "Ciudad":
                    paises = sorted(col_metric_data["COUNTRY"].dropna().unique())
                    pais_sel = st.selectbox(
                        "País (filtra las ciudades disponibles)",
                        paises,
                        key="trend_pais_para_ciudad",
                    )
                    sub_pais = col_metric_data[col_metric_data["COUNTRY"] == pais_sel]
                    opciones = sorted(sub_pais["CITY"].dropna().unique())
                    default_sel = opciones[: min(5, len(opciones))]
                    seleccion = st.multiselect(
                        "Ciudades a comparar",
                        opciones,
                        default=default_sel,
                        key="trend_ciudades",
                    )
                    df_plot_base = sub_pais[sub_pais["CITY"].isin(seleccion)]
                    df_plot = (
                        df_plot_base.groupby(["CITY", "WEEK_AGO"], as_index=False)["VALUE"]
                        .mean()
                        .rename(columns={"CITY": "grupo"})
                    )

                else:  # Zona
                    paises = sorted(col_metric_data["COUNTRY"].dropna().unique())
                    pais_sel = st.selectbox("País", paises, key="trend_pais_para_zona")
                    sub_pais = col_metric_data[col_metric_data["COUNTRY"] == pais_sel]
                    ciudades = sorted(sub_pais["CITY"].dropna().unique())
                    ciudad_sel = st.selectbox("Ciudad", ciudades, key="trend_ciudad_para_zona")
                    sub_ciudad = sub_pais[sub_pais["CITY"] == ciudad_sel]
                    opciones = sorted(sub_ciudad["ZONE"].dropna().unique())
                    default_sel = opciones[: min(5, len(opciones))]
                    seleccion = st.multiselect(
                        "Zonas a comparar",
                        opciones,
                        default=default_sel,
                        key="trend_zonas",
                    )
                    df_plot_base = sub_ciudad[sub_ciudad["ZONE"].isin(seleccion)]
                    df_plot = (
                        df_plot_base.groupby(["ZONE", "WEEK_AGO"], as_index=False)["VALUE"]
                        .mean()
                        .rename(columns={"ZONE": "grupo"})
                    )

                if df_plot.empty or not seleccion:
                    st.info("Selecciona al menos un elemento para graficar.")
                else:
                    df_plot = df_plot.sort_values("WEEK_AGO", ascending=False)
                    df_plot["semana"] = "L" + df_plot["WEEK_AGO"].astype(str) + "W"
                    semana_orden = [
                        f"L{w}W"
                        for w in sorted(df_plot["WEEK_AGO"].unique(), reverse=True)
                    ]

                    paleta = [
                        RAPPI_RED, RAPPI_CORAL, RAPPI_BROWN,
                        "#FF6B4A", "#7A2E1A", "#E89B8E",
                        "#B85040", "#FFAA8C", "#5C1F10", "#FFD9CC",
                    ]

                    chart = (
                        alt.Chart(df_plot)
                        .mark_line(point=alt.OverlayMarkDef(size=80), strokeWidth=3)
                        .encode(
                            x=alt.X(
                                "semana:N",
                                sort=semana_orden,
                                title="Semana (pasado → presente)",
                            ),
                            y=alt.Y("VALUE:Q", title=metric_trend),
                            color=alt.Color(
                                "grupo:N",
                                scale=alt.Scale(range=paleta),
                                legend=alt.Legend(title=nivel),
                            ),
                            tooltip=[
                                alt.Tooltip("grupo:N", title=nivel),
                                alt.Tooltip("semana:N", title="Semana"),
                                alt.Tooltip("VALUE:Q", title=metric_trend, format=".4f"),
                            ],
                        )
                        .properties(height=420)
                    )

                    st.altair_chart(chart, use_container_width=True)

                    with st.expander("Ver datos del gráfico"):
                        st.dataframe(
                            df_plot[["grupo", "semana", "VALUE"]].sort_values(
                                ["grupo", "semana"]
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
            # --------------------------------------------

            with sub_tabs[3]:
                st.markdown(
                    "##### Zonas divergentes vs sus pares (mismo país + ZONE_TYPE)"
                )
                if report["benchmarking"].empty:
                    st.info("Sin desviaciones significativas.")
                else:
                    st.dataframe(
                        report["benchmarking"],
                        use_container_width=True,
                        hide_index=True,
                    )

            with sub_tabs[4]:
                st.markdown("##### Pares de métricas con |r| ≥ 0.5")
                if report["correlaciones"].empty:
                    st.info("Sin correlaciones fuertes.")
                else:
                    st.dataframe(
                        report["correlaciones"],
                        use_container_width=True,
                        hide_index=True,
                    )

            # ---------------- OPORTUNIDADES (con chatbot) ----------------
            with sub_tabs[5]:
                st.markdown(
                    "##### Alta Lead Penetration + Bajo Perfect Orders (ROI alto)"
                )
                if report["oportunidades"].empty:
                    st.info("Sin oportunidades operacionales detectadas.")
                else:
                    st.dataframe(
                        report["oportunidades"],
                        use_container_width=True,
                        hide_index=True,
                    )

                    st.markdown("---")
                    st.markdown("#### 🤖 Análisis con IA + Conversación")
                    st.caption(
                        "Genera un análisis explicativo automático de las "
                        "oportunidades detectadas. Después puedes seguir "
                        "conversando para profundizar en zonas específicas."
                    )

                    # Empaqueta los datos como contexto para el LLM
                    df_op = report["oportunidades"]
                    contexto_oport = df_op.head(10).to_dict(orient="records")

                    SYSTEM_OPORT = """Eres un Senior Operations Strategist en Rappi.
Acabas de recibir una lista de zonas con OPORTUNIDADES OPERACIONALES detectadas:
zonas con ALTA Lead Penetration (mucha oferta de comercios habilitados) pero
BAJO Perfect Orders (mala calidad de ejecución: cancelaciones, demoras, defectos).

Tu trabajo es:
1. Cuando se te pida un análisis inicial, explica qué significan estos hallazgos
   en términos de negocio para Operations, Strategy y SP&A. Sé concreto, cita
   zonas y números. Estructura: hallazgo principal, causas probables, acciones
   recomendadas.
2. Cuando el usuario haga preguntas de seguimiento, profundiza usando el contexto
   de las oportunidades disponibles. Si pregunta por una zona puntual, usa los
   números reales de esa zona del contexto.
3. Sé directo y concreto. No uses muletillas ni introducciones largas. Habla
   en español.
4. Si la pregunta sale del contexto de oportunidades operacionales, redirige
   con tacto: "Eso es mejor responderlo en la pestaña Operations Bot, donde
   tengo acceso a toda la base."

CONTEXTO DE OPORTUNIDADES (top 10 zonas, JSON):
""" + json.dumps(contexto_oport, ensure_ascii=False, indent=2, default=str)

                    # Estado de la conversación de oportunidades
                    if "oport_messages" not in st.session_state:
                        st.session_state.oport_messages = []

                    col_a1, col_a2 = st.columns([1, 4])
                    with col_a1:
                        if st.button(
                            "🎯 Análisis inicial",
                            type="primary",
                            use_container_width=True,
                            key="btn_analisis_oport",
                        ):
                            with st.spinner("Generando análisis..."):
                                msgs = [
                                    {"role": "system", "content": SYSTEM_OPORT},
                                    {
                                        "role": "user",
                                        "content": (
                                            "Hazme un análisis explicativo de las "
                                            "oportunidades detectadas. ¿Qué cuenta "
                                            "esta tabla? ¿Cuáles son los hallazgos "
                                            "más importantes? ¿Qué debería hacer "
                                            "Operations primero?"
                                        ),
                                    },
                                ]
                                analisis = chat_gemini(msgs)
                            # Guardar como primer turno asistente
                            st.session_state.oport_messages = [
                                {
                                    "role": "user",
                                    "content": "Análisis inicial de las oportunidades",
                                },
                                {"role": "assistant", "content": analisis},
                            ]
                            st.rerun()
                    with col_a2:
                        if st.session_state.oport_messages:
                            if st.button(
                                "🧹 Reiniciar conversación",
                                key="reset_oport",
                            ):
                                st.session_state.oport_messages = []
                                st.rerun()

                    # Renderizar historial
                    for msg in st.session_state.oport_messages:
                        with st.chat_message(msg["role"]):
                            st.markdown(msg["content"])

                    # Input de seguimiento (solo si ya se generó análisis inicial)
                    if st.session_state.oport_messages:
                        prompt_op = st.chat_input(
                            "Ej: ¿Por qué Polanco aparece en la lista?",
                            key="chat_oport",
                        )
                        if prompt_op:
                            st.session_state.oport_messages.append(
                                {"role": "user", "content": prompt_op}
                            )
                            with st.chat_message("user"):
                                st.markdown(prompt_op)
                            with st.chat_message("assistant"):
                                with st.spinner("Pensando..."):
                                    # Reconstruir mensajes con system al inicio
                                    msgs = [{"role": "system", "content": SYSTEM_OPORT}]
                                    msgs.extend(st.session_state.oport_messages)
                                    respuesta = chat_gemini(msgs)
                                st.markdown(respuesta)
                            st.session_state.oport_messages.append(
                                {"role": "assistant", "content": respuesta}
                            )
            # --------------------------------------------------------------
