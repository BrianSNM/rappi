"""
Script standalone (uso único).

1) Lee todos los .json de data/json/
2) Los consolida en una tabla
3) Elimina filas donde subtotal, delivery_fee y service_fee son None al mismo tiempo
4) Elimina duplicados exactos
5) Guarda data/clean.parquet (rápido) y data/clean.csv (inspeccionable)

USO:
    python clean_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
JSON_DIR = DATA_DIR / "json"
OUT_PARQUET = DATA_DIR / "clean.parquet"
OUT_CSV = DATA_DIR / "clean.csv"


def main() -> None:
    if not JSON_DIR.exists():
        raise SystemExit(f"❌ No existe {JSON_DIR}")

    archivos = sorted(JSON_DIR.glob("*.json"))
    if not archivos:
        raise SystemExit(f"❌ No hay .json en {JSON_DIR}")

    # 1) Consolidar
    frames = []
    for path in archivos:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            continue
        df = pd.DataFrame(data)
        df["__source_file"] = path.name
        frames.append(df)
        print(f"  • {path.name}: {len(df):,} filas")

    df = pd.concat(frames, ignore_index=True)
    n0 = len(df)
    print(f"\n📥 Total consolidado: {n0:,} filas")

    # 2) Eliminar filas donde subtotal, delivery_fee y service_fee son None a la vez
    cols_money = ["subtotal", "delivery_fee", "service_fee"]
    faltan = [c for c in cols_money if c not in df.columns]
    if faltan:
        raise SystemExit(f"❌ Faltan columnas en los JSON: {faltan}")

    mask_all_none = df[cols_money].isna().all(axis=1)
    n_drop_none = int(mask_all_none.sum())
    df = df.loc[~mask_all_none].copy()
    print(f"🗑  Eliminadas por subtotal/delivery_fee/service_fee = None: {n_drop_none:,}")

    # 3) Eliminar duplicados exactos (sobre todas las columnas, ignorando archivo origen)
    cols_dedup = [c for c in df.columns if c != "__source_file"]
    n_before = len(df)
    df = df.drop_duplicates(subset=cols_dedup, keep="first").reset_index(drop=True)
    n_drop_dup = n_before - len(df)
    print(f"🗑  Eliminadas por duplicados exactos: {n_drop_dup:,}")

    # Tipar ts si existe (útil para análisis posterior)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")

    # 4) Guardar
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(OUT_PARQUET, index=False)
        print(f"\n💾 {OUT_PARQUET}  ({len(df):,} filas)")
    except ImportError:
        print("\n⚠ pyarrow no instalado, salto parquet. (pip install pyarrow)")

    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"💾 {OUT_CSV}     ({len(df):,} filas)")

    print("\n────────────── RESUMEN ──────────────")
    print(f"  Inicial:     {n0:,}")
    print(f"  Eliminadas:  {n_drop_none + n_drop_dup:,}")
    print(f"  Final:       {len(df):,}")
    print(f"  Reducción:   {(1 - len(df)/n0)*100:.1f}%")


if __name__ == "__main__":
    main()