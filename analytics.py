"""
analytics.py — Funciones estadísticas puras.

Cada función recibe un DataFrame filtrado y devuelve dicts/DataFrames.
No imprime, no usa Streamlit. Se recalcula automáticamente cuando
cambian los filtros o llegan datos nuevos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


# ---------- HELPERS ----------
def add_valor_total(df: pd.DataFrame) -> pd.DataFrame:
    """Añade columna valor_total = subtotal + delivery_fee + service_fee."""
    df = df.copy()
    df["valor_total"] = (
        df["subtotal"].fillna(0)
        + df["delivery_fee"].fillna(0)
        + df["service_fee"].fillna(0)
    )
    return df


def _bootstrap_diff_ci(
    a: np.ndarray, b: np.ndarray, n_boot: int = 5000, alpha: float = 0.05
) -> tuple[float, float, float]:
    """IC bootstrap para diferencia de medias (b - a). Devuelve (delta, lo, hi)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(42)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        ra = rng.choice(a, size=len(a), replace=True)
        rb = rng.choice(b, size=len(b), replace=True)
        deltas[i] = rb.mean() - ra.mean()
    return (
        float(b.mean() - a.mean()),
        float(np.percentile(deltas, 100 * alpha / 2)),
        float(np.percentile(deltas, 100 * (1 - alpha / 2))),
    )


# ---------- 1. KPIs GLOBALES ----------
def kpis_globales(df: pd.DataFrame) -> dict:
    """KPIs para tarjetas. Tolera df vacío."""
    if df.empty:
        return {k: 0 for k in [
            "n_registros", "n_direcciones", "n_plataformas", "n_ciudades",
            "subtotal_avg", "delivery_avg", "service_avg", "valor_total_avg",
        ]}
    df = add_valor_total(df)
    return {
        "n_registros": int(len(df)),
        "n_direcciones": int(df["address"].nunique()),
        "n_plataformas": int(df["platform"].nunique()),
        "n_ciudades": int(df["city"].nunique()),
        "subtotal_avg": float(df["subtotal"].mean()),
        "delivery_avg": float(df["delivery_fee"].mean()),
        "service_avg": float(df["service_fee"].mean()),
        "valor_total_avg": float(df["valor_total"].mean()),
    }


# ---------- 2. DISTRIBUCIÓN POR PLATAFORMA ----------
def distribucion_por_plataforma(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Estadísticos descriptivos por plataforma para una métrica."""
    if df.empty or metric not in df.columns:
        return pd.DataFrame()
    g = (
        df.groupby("platform")[metric]
        .agg(["count", "mean", "median", "std", "min", "max"])
        .round(2)
        .reset_index()
    )
    return g


# ---------- 3. COMPARATIVA PAREADA ENTRE PLATAFORMAS ----------
def comparativa_pareada(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """
    Para cada par de plataformas: delta de medias en datos pareados (misma
    address+producto), IC bootstrap, t-test pareado y Wilcoxon.

    Devuelve DataFrame con una fila por par.
    """
    if df.empty or metric not in df.columns:
        return pd.DataFrame()

    pivot = df.pivot_table(
        index=["address", "product_id"],
        columns="platform",
        values=metric,
        aggfunc="mean",
    )
    plataformas = sorted(pivot.columns)
    rows = []
    for i, p1 in enumerate(plataformas):
        for p2 in plataformas[i + 1:]:
            sub = pivot[[p1, p2]].dropna()
            n = len(sub)
            if n < 2:
                rows.append({
                    "platform_a": p1, "platform_b": p2,
                    "n_pareado": n, "delta_mean": np.nan,
                    "ci_low": np.nan, "ci_high": np.nan,
                    "t_pvalue": np.nan, "wilcoxon_pvalue": np.nan,
                    "a_more_expensive_pct": np.nan,
                })
                continue
            d = sub[p1] - sub[p2]
            delta, lo, hi = _bootstrap_diff_ci(sub[p2].values, sub[p1].values)
            try:
                t_p = stats.ttest_1samp(d, 0).pvalue
            except Exception:
                t_p = np.nan
            try:
                if (d != 0).any():
                    w_p = stats.wilcoxon(d).pvalue
                else:
                    w_p = 1.0
            except Exception:
                w_p = np.nan
            rows.append({
                "platform_a": p1, "platform_b": p2,
                "n_pareado": int(n),
                "delta_mean": round(float(d.mean()), 2),
                "ci_low": round(lo, 2),
                "ci_high": round(hi, 2),
                "t_pvalue": round(float(t_p), 4),
                "wilcoxon_pvalue": round(float(w_p), 4),
                "a_more_expensive_pct": round(float((d > 0).mean() * 100), 1),
            })
    return pd.DataFrame(rows)


# ---------- 4. COBERTURA COMPETITIVA ----------
def cobertura_competitiva(df: pd.DataFrame) -> dict:
    """Mapas de presencia plataforma × ciudad y plataforma × tier."""
    if df.empty:
        return {"por_ciudad": pd.DataFrame(), "por_tier": pd.DataFrame(),
                "por_zona": pd.DataFrame()}
    return {
        "por_ciudad": df.groupby(["platform", "city"]).size().unstack(fill_value=0),
        "por_tier": df.groupby(["platform", "tier"]).size().unstack(fill_value=0),
        "por_zona": df.groupby(["platform", "zone_id"]).size().unstack(fill_value=0),
    }


# ---------- 5. ESTRUCTURA DE FEES ----------
def estructura_de_fees(df: pd.DataFrame) -> pd.DataFrame:
    """Composición porcentual del valor total por plataforma."""
    if df.empty:
        return pd.DataFrame()
    df = add_valor_total(df)
    df = df[df["valor_total"] > 0].copy()
    df["subtotal_pct"] = df["subtotal"] / df["valor_total"] * 100
    df["delivery_pct"] = df["delivery_fee"] / df["valor_total"] * 100
    df["service_pct"] = df["service_fee"] / df["valor_total"] * 100
    return (
        df.groupby("platform")[["subtotal_pct", "delivery_pct", "service_pct"]]
        .mean()
        .round(2)
        .reset_index()
    )


# ---------- 6. CONSISTENCIA DE PRECIO ----------
def consistencia_precios(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coeficiente de variación (CV%) del subtotal por producto × plataforma.
    CV alto = precio inconsistente entre direcciones.
    """
    if df.empty:
        return pd.DataFrame()

    def cv(s):
        m = s.mean()
        return (s.std() / m * 100) if m else np.nan

    g = (
        df.groupby(["product_id", "platform"])["subtotal"]
        .agg(["count", "mean", "std", cv])
        .round(2)
        .rename(columns={"cv": "cv_pct"})
        .reset_index()
    )
    return g


# ---------- 7. VARIABILIDAD GEOGRÁFICA ----------
def variabilidad_geografica(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Promedio de una métrica por (city, tier, platform)."""
    if df.empty or metric not in df.columns:
        return pd.DataFrame()
    return (
        df.groupby(["city", "tier", "platform"])[metric]
        .mean()
        .round(2)
        .reset_index()
    )


# ---------- 8. RESUMEN COMPLETO PARA IA ----------
def resumen_para_ia(df: pd.DataFrame) -> dict:
    """
    Empaqueta TODOS los estadísticos en un dict serializable para
    enviar al LLM como contexto único.
    """
    if df.empty:
        return {"error": "DataFrame vacío"}

    out = {
        "filtros_aplicados": {
            "n_registros": int(len(df)),
            "ciudades": sorted(df["city"].dropna().unique().tolist()),
            "plataformas": sorted(df["platform"].dropna().unique().tolist()),
            "productos": sorted(df["product_id"].dropna().unique().tolist()),
            "tiers": sorted(df["tier"].dropna().unique().tolist()),
            "n_direcciones": int(df["address"].nunique()),
        },
        "kpis": kpis_globales(df),
    }

    for metric in ["subtotal", "delivery_fee", "service_fee"]:
        out[f"distribucion_{metric}"] = (
            distribucion_por_plataforma(df, metric).to_dict(orient="records")
        )
        out[f"pareado_{metric}"] = (
            comparativa_pareada(df, metric).to_dict(orient="records")
        )

    out["estructura_fees"] = estructura_de_fees(df).to_dict(orient="records")
    out["consistencia_precios"] = consistencia_precios(df).to_dict(orient="records")

    cob = cobertura_competitiva(df)
    out["cobertura_por_ciudad"] = cob["por_ciudad"].to_dict() if not cob["por_ciudad"].empty else {}
    out["cobertura_por_tier"] = cob["por_tier"].to_dict() if not cob["por_tier"].empty else {}

    return out
