"""
Script standalone (uso único / on-demand).

Toma data/clean.csv y hace left join con data/geocache.json
para añadir las columnas `lat` y `lon` a partir de `address`.

Sobreescribe data/clean.csv con el resultado.

USO:
    python merge_coords.py
"""
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
CLEAN_CSV = DATA_DIR / "clean.csv"
GEOCACHE = DATA_DIR / "geocache.json"


def main() -> None:
    if not CLEAN_CSV.exists():
        raise SystemExit(f"❌ No existe {CLEAN_CSV}. Corre primero clean_data.py")
    if not GEOCACHE.exists():
        raise SystemExit(f"❌ No existe {GEOCACHE}. Corre primero geocode_addresses.py")

    df = pd.read_csv(CLEAN_CSV)
    print(f"📥 {CLEAN_CSV.name}: {len(df):,} filas")

    if "address" not in df.columns:
        raise SystemExit("❌ clean.csv no tiene columna 'address'")

    raw = json.loads(GEOCACHE.read_text(encoding="utf-8"))
    coords_rows = [
        {"address": addr, "lat": v[0], "lon": v[1]}
        for addr, v in raw.items()
        if v is not None
    ]
    df_coords = pd.DataFrame(coords_rows)
    print(f"📍 geocache.json: {len(raw)} totales, {len(df_coords)} con coordenadas")

    # Si ya existían columnas lat/lon, las sobrescribimos
    df = df.drop(columns=[c for c in ("lat", "lon") if c in df.columns])

    df_out = df.merge(df_coords, on="address", how="left")

    matched = df_out["lat"].notna().sum()
    sin = len(df_out) - matched
    print(f"\n🔗 Match: {matched:,} / {len(df_out):,}")
    if sin:
        print(f"⚠ {sin:,} filas sin coordenadas")
        sin_addr = df_out.loc[df_out["lat"].isna(), "address"].dropna().unique()
        print(f"   Addresses únicas sin match: {len(sin_addr)}")
        for a in list(sin_addr)[:10]:
            print(f"     • {a}")
        if len(sin_addr) > 10:
            print(f"     … y {len(sin_addr) - 10} más")

    df_out.to_csv(CLEAN_CSV, index=False, encoding="utf-8")
    print(f"\n💾 Sobrescrito: {CLEAN_CSV} ({len(df_out):,} filas, "
          f"{len(df_out.columns)} columnas)")
    print(f"   Columnas: {list(df_out.columns)}")


if __name__ == "__main__":
    main()
