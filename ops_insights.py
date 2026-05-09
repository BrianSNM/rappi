"""
ops_insights.py — Sistema de insights automáticos sobre master_data.

Categorías generadas:
1. Anomalías: cambios drásticos L1W → L0W (>10%)
2. Tendencias deteriorándose: pendiente negativa 3+ semanas consecutivas
3. Benchmarking: zonas similares (mismo país + ZONE_TYPE) con performance divergente
4. Correlaciones: pares de métricas con relación fuerte a nivel zona
5. Oportunidades: zonas con buen Lead Penetration pero mal Perfect Orders, etc.

Cada función devuelve un DataFrame ordenado por relevancia.
La función `generate_executive_report()` consolida todo en markdown.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ---------- HELPERS ----------
def _pivot_metric_weeks(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Devuelve pivot zone × week para una métrica. Filas = zona+país+ciudad."""
    sub = df[df["METRIC"] == metric].copy()
    if sub.empty:
        return pd.DataFrame()
    return sub.pivot_table(
        index=["COUNTRY", "CITY", "ZONE", "ZONE_TYPE"],
        columns="WEEK_AGO",
        values="VALUE",
        aggfunc="mean",
    )


# ---------- 1. ANOMALÍAS ----------
def detectar_anomalias(df: pd.DataFrame, threshold: float = 0.10) -> pd.DataFrame:
    """
    Zonas con cambios > threshold (10% por defecto) entre L1W y L0W.

    Devuelve DataFrame con: COUNTRY, ZONE, METRIC, valor_l1w, valor_l0w, cambio_pct, direccion.
    """
    rows = []
    for metric in df["METRIC"].unique():
        pv = _pivot_metric_weeks(df, metric)
        if pv.empty or 0 not in pv.columns or 1 not in pv.columns:
            continue
        sub = pv[[1, 0]].dropna()
        if sub.empty:
            continue
        sub = sub.rename(columns={1: "valor_l1w", 0: "valor_l0w"})
        sub["cambio_abs"] = sub["valor_l0w"] - sub["valor_l1w"]
        # Evitar divisiones por cero
        denom = sub["valor_l1w"].replace(0, np.nan).abs()
        sub["cambio_pct"] = (sub["cambio_abs"] / denom * 100).round(2)
        sub = sub.dropna(subset=["cambio_pct"])
        criticos = sub[sub["cambio_pct"].abs() >= threshold * 100].copy()
        if criticos.empty:
            continue
        criticos["METRIC"] = metric
        criticos["direccion"] = np.where(
            criticos["cambio_pct"] > 0, "📈 mejora", "📉 deterioro"
        )
        rows.append(criticos.reset_index())

    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values("cambio_pct", key=abs, ascending=False)
    return out[
        ["COUNTRY", "CITY", "ZONE", "ZONE_TYPE", "METRIC",
         "valor_l1w", "valor_l0w", "cambio_pct", "direccion"]
    ].round(3)


# ---------- 2. TENDENCIAS DETERIORÁNDOSE ----------
def detectar_tendencias_negativas(
    df: pd.DataFrame, min_semanas: int = 3
) -> pd.DataFrame:
    """
    Zonas donde una métrica viene decreciendo `min_semanas` o más consecutivas.

    Para cada zona × métrica calcula la pendiente de la regresión simple sobre
    las últimas 8 semanas. Si la pendiente es negativa Y los últimos
    `min_semanas` valores son monotónicamente decrecientes (de pasado a presente),
    se reporta.

    Recordá: WEEK_AGO=8 es pasado, WEEK_AGO=0 es presente.
    """
    rows = []
    for metric in df["METRIC"].unique():
        pv = _pivot_metric_weeks(df, metric)
        if pv.empty:
            continue
        # Reordenar columnas de pasado a presente: 8, 7, ..., 0
        cols_orden = sorted(pv.columns, reverse=True)
        pv = pv[cols_orden]

        for idx, row in pv.iterrows():
            valores = row.dropna().values
            if len(valores) < min_semanas + 1:
                continue
            # Pendiente sobre todas las semanas disponibles
            x = np.arange(len(valores))
            try:
                slope = np.polyfit(x, valores, 1)[0]
            except (np.linalg.LinAlgError, ValueError):
                continue
            if slope >= 0:
                continue
            # Verificar monotonía descendente en las últimas min_semanas
            ultimas = valores[-min_semanas:]
            if all(ultimas[i] > ultimas[i + 1] for i in range(len(ultimas) - 1)):
                country, city, zone, zone_type = idx
                rows.append({
                    "COUNTRY": country,
                    "CITY": city,
                    "ZONE": zone,
                    "ZONE_TYPE": zone_type,
                    "METRIC": metric,
                    "valor_inicial": round(float(valores[0]), 3),
                    "valor_actual": round(float(valores[-1]), 3),
                    "pendiente": round(float(slope), 4),
                    "n_semanas": len(valores),
                })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("pendiente")


# ---------- 3. BENCHMARKING ----------
def detectar_outliers_benchmarking(
    df: pd.DataFrame, week: int = 0, n_std: float = 1.5
) -> pd.DataFrame:
    """
    Para cada (COUNTRY, ZONE_TYPE, METRIC), calcula media y std en la semana dada
    y reporta zonas que se desvían más de n_std de su grupo.

    Esto identifica zonas con performance divergente respecto a sus pares similares.
    """
    sub = df[df["WEEK_AGO"] == week].dropna(subset=["VALUE"]).copy()
    if sub.empty:
        return pd.DataFrame()

    # Calcular media y std por grupo
    grp = sub.groupby(["COUNTRY", "ZONE_TYPE", "METRIC"])["VALUE"]
    sub["grupo_mean"] = grp.transform("mean")
    sub["grupo_std"] = grp.transform("std")
    sub["grupo_n"] = grp.transform("count")

    # Solo grupos con al menos 3 zonas
    sub = sub[sub["grupo_n"] >= 3]
    if sub.empty:
        return pd.DataFrame()

    sub["z_score"] = (sub["VALUE"] - sub["grupo_mean"]) / sub["grupo_std"]
    sub = sub.dropna(subset=["z_score"])
    outliers = sub[sub["z_score"].abs() >= n_std].copy()
    if outliers.empty:
        return pd.DataFrame()

    outliers["direccion"] = np.where(
        outliers["z_score"] > 0, "✅ destaca arriba", "⚠ destaca abajo"
    )
    return (
        outliers[[
            "COUNTRY", "CITY", "ZONE", "ZONE_TYPE", "METRIC",
            "VALUE", "grupo_mean", "z_score", "direccion",
        ]]
        .sort_values("z_score", key=abs, ascending=False)
        .round(3)
    )


# ---------- 4. CORRELACIONES ----------
def detectar_correlaciones(
    df: pd.DataFrame, week: int = 0, min_abs_corr: float = 0.5
) -> pd.DataFrame:
    """
    Pares de métricas con correlación |r| >= min_abs_corr a nivel zona en una semana.
    """
    sub = df[df["WEEK_AGO"] == week].dropna(subset=["VALUE"])
    if sub.empty:
        return pd.DataFrame()
    pivot = sub.pivot_table(
        index=["COUNTRY", "ZONE"],
        columns="METRIC",
        values="VALUE",
        aggfunc="mean",
    )
    if pivot.shape[1] < 2:
        return pd.DataFrame()

    corr = pivot.corr()
    rows = []
    metrics = corr.columns.tolist()
    for i, m1 in enumerate(metrics):
        for m2 in metrics[i + 1:]:
            r = corr.loc[m1, m2]
            if pd.notna(r) and abs(r) >= min_abs_corr:
                # Calcular n efectivo
                n = pivot[[m1, m2]].dropna().shape[0]
                rows.append({
                    "metrica_a": m1,
                    "metrica_b": m2,
                    "correlacion": round(float(r), 3),
                    "n_zonas": int(n),
                    "tipo": "positiva ↗" if r > 0 else "negativa ↘",
                })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("correlacion", key=abs, ascending=False)


# ---------- 5. OPORTUNIDADES ----------
def detectar_oportunidades(df: pd.DataFrame, week: int = 0) -> pd.DataFrame:
    """
    Zonas con alto Lead Penetration pero bajo Perfect Orders.
    Indicador: ya tenemos la oferta pero la experiencia falla.
    """
    sub = df[df["WEEK_AGO"] == week].copy()
    if sub.empty:
        return pd.DataFrame()

    pivot = sub.pivot_table(
        index=["COUNTRY", "CITY", "ZONE", "ZONE_TYPE"],
        columns="METRIC",
        values="VALUE",
        aggfunc="mean",
    )

    if "Lead Penetration" not in pivot.columns or "Perfect Orders" not in pivot.columns:
        return pd.DataFrame()

    pares = pivot[["Lead Penetration", "Perfect Orders"]].dropna()
    if pares.empty:
        return pd.DataFrame()

    lp_median = pares["Lead Penetration"].median()
    po_median = pares["Perfect Orders"].median()

    oport = pares[
        (pares["Lead Penetration"] > lp_median)
        & (pares["Perfect Orders"] < po_median)
    ].copy()

    if oport.empty:
        return pd.DataFrame()

    oport["gap_perfect_orders"] = (po_median - oport["Perfect Orders"]).round(3)
    oport = oport.sort_values("gap_perfect_orders", ascending=False)
    return oport.reset_index().round(3)


# ---------- REPORTE EJECUTIVO ----------
def _section_anomalias(df_an: pd.DataFrame, top_n: int = 5) -> str:
    if df_an.empty:
        return "_No se detectaron anomalías significativas (cambios > 10% L1W → L0W)._\n"
    out = []
    deterioros = df_an[df_an["direccion"].str.contains("deterioro")].head(top_n)
    if not deterioros.empty:
        out.append(f"**Top {len(deterioros)} deterioros (L1W → L0W):**\n")
        for _, r in deterioros.iterrows():
            out.append(
                f"- **{r['ZONE']}** ({r['COUNTRY']} · {r['ZONE_TYPE']}) — "
                f"{r['METRIC']}: {r['valor_l1w']:.3f} → {r['valor_l0w']:.3f} "
                f"({r['cambio_pct']:+.1f}%)"
            )
        out.append("")
    mejoras = df_an[df_an["direccion"].str.contains("mejora")].head(top_n)
    if not mejoras.empty:
        out.append(f"**Top {len(mejoras)} mejoras (L1W → L0W):**\n")
        for _, r in mejoras.iterrows():
            out.append(
                f"- **{r['ZONE']}** ({r['COUNTRY']}) — "
                f"{r['METRIC']}: {r['valor_l1w']:.3f} → {r['valor_l0w']:.3f} "
                f"({r['cambio_pct']:+.1f}%)"
            )
    return "\n".join(out) + "\n"


def _section_tendencias(df_t: pd.DataFrame, top_n: int = 5) -> str:
    if df_t.empty:
        return "_No se detectaron tendencias deteriorándose por 3+ semanas consecutivas._\n"
    out = [f"**Top {min(len(df_t), top_n)} tendencias en deterioro sostenido:**\n"]
    for _, r in df_t.head(top_n).iterrows():
        out.append(
            f"- **{r['ZONE']}** ({r['COUNTRY']}) — {r['METRIC']}: "
            f"{r['valor_inicial']:.3f} → {r['valor_actual']:.3f} "
            f"(pendiente {r['pendiente']:+.4f}, {r['n_semanas']} semanas)"
        )
    return "\n".join(out) + "\n"


def _section_benchmarking(df_b: pd.DataFrame, top_n: int = 5) -> str:
    if df_b.empty:
        return "_Sin desviaciones significativas dentro de grupos comparables._\n"
    out = [f"**Top {min(len(df_b), top_n)} zonas divergentes vs sus pares:**\n"]
    for _, r in df_b.head(top_n).iterrows():
        out.append(
            f"- **{r['ZONE']}** ({r['COUNTRY']} · {r['ZONE_TYPE']}) — "
            f"{r['METRIC']}: {r['VALUE']:.3f} vs grupo {r['grupo_mean']:.3f} "
            f"(z={r['z_score']:+.2f}, {r['direccion']})"
        )
    return "\n".join(out) + "\n"


def _section_correlaciones(df_c: pd.DataFrame, top_n: int = 5) -> str:
    if df_c.empty:
        return "_Sin correlaciones fuertes (|r| ≥ 0.5) entre métricas._\n"
    out = [f"**Top {min(len(df_c), top_n)} correlaciones entre métricas (semana actual):**\n"]
    for _, r in df_c.head(top_n).iterrows():
        out.append(
            f"- {r['metrica_a']} ↔ {r['metrica_b']}: "
            f"r = {r['correlacion']:+.2f} ({r['tipo']}, n={r['n_zonas']} zonas)"
        )
    return "\n".join(out) + "\n"


def _section_oportunidades(df_o: pd.DataFrame, top_n: int = 5) -> str:
    if df_o.empty:
        return "_No se detectaron zonas con alta penetración pero baja calidad de servicio._\n"
    out = [
        f"**Top {min(len(df_o), top_n)} oportunidades operacionales** "
        "(alta Lead Penetration + bajo Perfect Orders):\n"
    ]
    for _, r in df_o.head(top_n).iterrows():
        out.append(
            f"- **{r['ZONE']}** ({r['COUNTRY']} · {r['ZONE_TYPE']}) — "
            f"Lead Pen: {r['Lead Penetration']:.3f} · "
            f"Perfect Orders: {r['Perfect Orders']:.3f} "
            f"(gap vs mediana: {r['gap_perfect_orders']:+.3f})"
        )
    return "\n".join(out) + "\n"


def generate_executive_report(df: pd.DataFrame) -> dict[str, Any]:
    """
    Calcula los 5 análisis y devuelve dict con DataFrames + reporte markdown.
    """
    anomalias = detectar_anomalias(df, threshold=0.10)
    tendencias = detectar_tendencias_negativas(df, min_semanas=3)
    benchmarking = detectar_outliers_benchmarking(df, week=0, n_std=1.5)
    correlaciones = detectar_correlaciones(df, week=0, min_abs_corr=0.5)
    oportunidades = detectar_oportunidades(df, week=0)

    # Resumen ejecutivo: top 5 hallazgos críticos
    resumen = []
    if not anomalias.empty:
        det = anomalias[anomalias["direccion"].str.contains("deterioro")].head(2)
        for _, r in det.iterrows():
            resumen.append(
                f"⚠ **Deterioro abrupto** en {r['ZONE']} ({r['COUNTRY']}): "
                f"{r['METRIC']} cayó {r['cambio_pct']:+.1f}% en 1 semana."
            )
    if not tendencias.empty:
        r = tendencias.iloc[0]
        resumen.append(
            f"📉 **Tendencia sostenida** en {r['ZONE']} ({r['COUNTRY']}): "
            f"{r['METRIC']} viene cayendo {r['n_semanas']} semanas seguidas."
        )
    if not oportunidades.empty:
        r = oportunidades.iloc[0]
        resumen.append(
            f"💡 **Oportunidad operacional** en {r['ZONE']} ({r['COUNTRY']}): "
            f"alta penetración pero Perfect Orders {r['gap_perfect_orders']:.3f} "
            f"bajo la mediana."
        )
    if not benchmarking.empty:
        bajos = benchmarking[benchmarking["direccion"].str.contains("abajo")].head(1)
        if not bajos.empty:
            r = bajos.iloc[0]
            resumen.append(
                f"🔍 **Outlier negativo** en {r['ZONE']} ({r['COUNTRY']}): "
                f"{r['METRIC']} a {r['z_score']:+.2f} std de sus pares."
            )
    if not correlaciones.empty:
        r = correlaciones.iloc[0]
        resumen.append(
            f"🔗 **Correlación fuerte**: {r['metrica_a']} ↔ {r['metrica_b']} "
            f"(r = {r['correlacion']:+.2f})."
        )

    if not resumen:
        resumen.append("_No se detectaron hallazgos críticos en este corte._")

    # Recomendaciones por categoría
    reco = {
        "anomalias": (
            "**Acción Operations:** auditar inmediatamente los deterioros >10% "
            "L1W→L0W. Validar si responden a un evento puntual (caída de partners, "
            "cambio de pricing) o a un problema sostenido."
        ),
        "tendencias": (
            "**Acción Strategy:** las zonas con 3+ semanas en deterioro requieren "
            "intervención. Cada semana adicional sin acción reduce la probabilidad "
            "de recuperación. Priorizar las de mayor pendiente negativa."
        ),
        "benchmarking": (
            "**Acción SP&A:** las zonas que se desvían >1.5 std de sus pares son "
            "candidatas a deep-dive. Si están abajo, copiar el playbook de las que "
            "destacan arriba en el mismo grupo."
        ),
        "correlaciones": (
            "**Acción Analytics:** validar si las correlaciones detectadas implican "
            "causalidad operativa. Si Lead Penetration correlaciona con Conversión, "
            "subir Lead Penetration en zonas estancadas podría mover la conversión."
        ),
        "oportunidades": (
            "**Acción Operations:** zonas con alta oferta pero mala experiencia "
            "tienen el mayor ROI por intervención. La oferta ya está; el problema "
            "es ejecución (cancelaciones, demoras, defectos)."
        ),
    }

    md = []
    md.append("## Resumen Ejecutivo\n")
    for item in resumen:
        md.append(f"- {item}")
    md.append("\n---\n")
    md.append("## 1. Anomalías (cambios > 10% L1W → L0W)\n")
    md.append(_section_anomalias(anomalias))
    md.append(reco["anomalias"])
    md.append("\n---\n")
    md.append("## 2. Tendencias deteriorándose (3+ semanas consecutivas)\n")
    md.append(_section_tendencias(tendencias))
    md.append(reco["tendencias"])
    md.append("\n---\n")
    md.append("## 3. Benchmarking (zonas divergentes vs sus pares)\n")
    md.append(_section_benchmarking(benchmarking))
    md.append(reco["benchmarking"])
    md.append("\n---\n")
    md.append("## 4. Correlaciones entre métricas\n")
    md.append(_section_correlaciones(correlaciones))
    md.append(reco["correlaciones"])
    md.append("\n---\n")
    md.append("## 5. Oportunidades operacionales\n")
    md.append(_section_oportunidades(oportunidades))
    md.append(reco["oportunidades"])

    return {
        "markdown": "\n".join(md),
        "anomalias": anomalias,
        "tendencias": tendencias,
        "benchmarking": benchmarking,
        "correlaciones": correlaciones,
        "oportunidades": oportunidades,
    }
