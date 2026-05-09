import json
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

PLATFORMS = ["rappi", "uber", "didi"]
METRICS = ["subtotal", "delivery_fee", "service_fee", "eta_min"]


def load_records(raw_dir: str = "data/raw") -> pd.DataFrame:
    rows = []
    for f in Path(raw_dir).glob("*.json"):
        rows.extend(json.loads(f.read_text()))
    return pd.DataFrame(rows)


def build_tensor(df: pd.DataFrame, products: list[str], zones: list[str]) -> tuple[np.ndarray, dict]:
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df["bucket"] = df["ts"].dt.floor("90min")
    buckets = sorted(df["bucket"].unique())

    P, PL, M, Z, T = len(products), len(PLATFORMS), len(METRICS), len(zones), len(buckets)
    tensor = np.full((P, PL, M, Z, T), np.nan, dtype=np.float32)

    p_idx = {v: i for i, v in enumerate(products)}
    pl_idx = {v: i for i, v in enumerate(PLATFORMS)}
    m_idx = {v: i for i, v in enumerate(METRICS)}
    z_idx = {v: i for i, v in enumerate(zones)}
    t_idx = {v: i for i, v in enumerate(buckets)}

    for r in df.itertuples():
        if r.product_id not in p_idx or r.zone_id not in z_idx or r.platform not in pl_idx:
            continue
        for m in METRICS:
            v = getattr(r, m, None)
            if v is None or pd.isna(v):
                continue
            tensor[p_idx[r.product_id], pl_idx[r.platform], m_idx[m], z_idx[r.zone_id], t_idx[r.bucket]] = float(v)

    coords = {
        "product": products, "platform": PLATFORMS, "metric": METRICS,
        "zone": zones, "time": [str(b) for b in buckets],
    }
    return tensor, coords


def total_price(tensor: np.ndarray) -> np.ndarray:
    sub = tensor[:, :, METRICS.index("subtotal"), :, :]
    deli = np.nan_to_num(tensor[:, :, METRICS.index("delivery_fee"), :, :], nan=0)
    svc = np.nan_to_num(tensor[:, :, METRICS.index("service_fee"), :, :], nan=0)
    return sub + deli + svc


def competitiveness_index(tensor: np.ndarray) -> np.ndarray:
    total = total_price(tensor)
    rappi = total[:, PLATFORMS.index("rappi"), :, :]
    competitors = np.nanmean(np.delete(total, PLATFORMS.index("rappi"), axis=1), axis=1)
    return (competitors - rappi) / competitors


def zone_summary(tensor: np.ndarray, coords: dict) -> pd.DataFrame:
    ci = competitiveness_index(tensor)
    avg_ci_by_zone = np.nanmean(ci, axis=(0, 2))
    total = np.nanmean(total_price(tensor), axis=(0, 3))
    eta = np.nanmean(tensor[:, :, METRICS.index("eta_min"), :, :], axis=(0, 3))
    rows = []
    for i, z in enumerate(coords["zone"]):
        rows.append({
            "zone": z,
            "competitiveness_index": float(avg_ci_by_zone[i]) if not np.isnan(avg_ci_by_zone[i]) else None,
            "rappi_total": float(total[PLATFORMS.index("rappi"), i]) if not np.isnan(total[PLATFORMS.index("rappi"), i]) else None,
            "uber_total": float(total[PLATFORMS.index("uber"), i]) if not np.isnan(total[PLATFORMS.index("uber"), i]) else None,
            "didi_total": float(total[PLATFORMS.index("didi"), i]) if not np.isnan(total[PLATFORMS.index("didi"), i]) else None,
            "rappi_eta": float(eta[PLATFORMS.index("rappi"), i]) if not np.isnan(eta[PLATFORMS.index("rappi"), i]) else None,
        })
    return pd.DataFrame(rows)


def driver_breakdown(tensor: np.ndarray, zone_idx: int) -> dict:
    rappi_i = PLATFORMS.index("rappi")
    means = np.nanmean(tensor[:, :, :, zone_idx, :], axis=(0, 3))
    rappi_metrics = means[rappi_i]
    comp_metrics = np.nanmean(np.delete(means, rappi_i, axis=0), axis=0)
    diffs = {METRICS[i]: float(rappi_metrics[i] - comp_metrics[i]) for i in range(len(METRICS))}
    return diffs


def generate_insight_text(zone: str, ci: Optional[float], drivers: dict) -> str:
    if ci is None or np.isnan(ci):
        return f"Zona {zone}: datos insuficientes."
    pct = abs(ci) * 100
    direction = "mas barato" if ci > 0 else "mas caro"
    main_driver = max(drivers.items(), key=lambda kv: abs(kv[1]) if not np.isnan(kv[1]) else 0)
    return f"En {zone}, Rappi es {pct:.1f}% {direction} que la competencia. Driver principal: {main_driver[0]} (diff {main_driver[1]:+.2f})."
