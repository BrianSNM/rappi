import json
from pathlib import Path
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from src.analytics import (
    load_records, build_tensor, competitiveness_index,
    zone_summary, driver_breakdown, generate_insight_text, PLATFORMS, METRICS,
)

st.set_page_config(page_title="Rappi Competitive Intelligence", layout="wide")

zones_cfg = json.loads(Path("config/zones.json").read_text())["zones"]
products_cfg = json.loads(Path("config/products.json").read_text())["products"]
zones_by_id = {z["id"]: z for z in zones_cfg}

df = load_records()
if df.empty:
    st.warning("No hay datos en data/raw. Ejecuta `python run_scraper.py` primero.")
    st.stop()

tensor, coords = build_tensor(df, [p["id"] for p in products_cfg], [z["id"] for z in zones_cfg])

st.sidebar.header("Filtros")
city_filter = st.sidebar.multiselect("Ciudad", sorted({z["city"] for z in zones_cfg}), default=None)
product_filter = st.sidebar.multiselect("Producto", coords["product"], default=coords["product"])
time_filter = st.sidebar.selectbox("Momento", ["Todos"] + coords["time"])

p_mask = [coords["product"].index(p) for p in product_filter]
t_mask = list(range(len(coords["time"]))) if time_filter == "Todos" else [coords["time"].index(time_filter)]

sub = tensor[p_mask][:, :, :, :, t_mask]
ci = competitiveness_index(sub)
ci_zone = np.nanmean(ci, axis=(0, 2))

map_rows = []
for i, z_id in enumerate(coords["zone"]):
    z = zones_by_id[z_id]
    if city_filter and z["city"] not in city_filter:
        continue
    val = ci_zone[i]
    if np.isnan(val):
        color = [120, 120, 120]
    elif val > 0.05:
        color = [0, 180, 80]
    elif val < -0.05:
        color = [220, 60, 60]
    else:
        color = [240, 200, 0]
    map_rows.append({
        "zone": z_id, "city": z["city"], "lat": z["lat"], "lng": z["lng"],
        "ci": float(val) if not np.isnan(val) else None,
        "color": color, "radius": 1500,
    })
map_df = pd.DataFrame(map_rows)

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Mapa de competitividad")
    if not map_df.empty:
        layer = pdk.Layer(
            "ScatterplotLayer", data=map_df,
            get_position=["lng", "lat"], get_fill_color="color",
            get_radius="radius", pickable=True, opacity=0.7,
        )
        view = pdk.ViewState(latitude=map_df["lat"].mean(), longitude=map_df["lng"].mean(), zoom=4.5)
        st.pydeck_chart(pdk.Deck(
            layers=[layer], initial_view_state=view,
            tooltip={"text": "{zone}\nCI: {ci}"},
            map_style="light",
        ))

with col2:
    st.subheader("Top insights")
    summary = zone_summary(sub, {**coords, "product": product_filter, "time": [coords["time"][i] for i in t_mask]})
    summary = summary.dropna(subset=["competitiveness_index"]).reindex(
        summary["competitiveness_index"].abs().sort_values(ascending=False).index
    ).head(5)
    for _, row in summary.iterrows():
        zi = coords["zone"].index(row["zone"])
        drv = driver_breakdown(sub, zi)
        st.info(generate_insight_text(row["zone"], row["competitiveness_index"], drv))

st.subheader("Resumen por zona")
st.dataframe(zone_summary(sub, coords).round(2), use_container_width=True)
