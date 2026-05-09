"""
Script standalone (uso único / on-demand).

Lee todos los JSON de data/json/, extrae addresses únicas y las geocodifica
con Nominatim (OpenStreetMap). Guarda el resultado en data/geocache.json.

USO:
    python geocode_addresses.py             # solo direcciones nuevas
    python geocode_addresses.py --refresh   # re-geocodifica todo desde cero
    python geocode_addresses.py --retry     # reintenta solo las que fallaron

Después la app simplemente lee data/geocache.json (ya no llama a la red).

Política Nominatim: 1 req/seg + User-Agent identificable.
https://operations.osmfoundation.org/policies/nominatim/
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


DATA_DIR = Path(__file__).parent / "data"
JSON_DIR = DATA_DIR / "json"
CACHE_PATH = DATA_DIR / "geocache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "rappi-intel/1.0 (internal-tool)"
REQUEST_DELAY_SEC = 1.1


def _nominatim_one(query: str, timeout: int = 10) -> Optional[tuple[float, float]]:
    url = f"{NOMINATIM_URL}?q={quote(query)}&format=json&limit=1"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data:
            return None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except (URLError, HTTPError, ValueError, KeyError):
        return None


def _build_fallback_queries(address: str) -> list[str]:
    """
    Variantes cada vez más generales para aumentar tasa de resolución.

    "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"
      → la dirección completa
      → "Polanco, Miguel Hidalgo, 11560 CDMX"
      → "Miguel Hidalgo, 11560 CDMX"
      → "11560 CDMX"
    """
    queries = [address]
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 2:
        queries.append(", ".join(parts[1:]))
    if len(parts) >= 3:
        queries.append(", ".join(parts[-3:]))
    if len(parts) >= 2:
        queries.append(", ".join(parts[-2:]))
    if parts:
        queries.append(parts[-1])
    seen = set()
    out = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def query_address(address: str) -> Optional[tuple[float, float]]:
    """Intenta query exacto y luego variantes hasta encontrar coordenadas."""
    queries = _build_fallback_queries(address)
    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(REQUEST_DELAY_SEC)
        result = _nominatim_one(q)
        if result is not None:
            return result
    return None


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"⚠ Cache corrupto en {CACHE_PATH}, ignorando")
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def collect_addresses() -> list[str]:
    """Lee todos los JSON de data/json y devuelve addresses únicas."""
    if not JSON_DIR.exists():
        print(f"❌ No existe {JSON_DIR}")
        sys.exit(1)
    addresses = set()
    archivos = sorted(JSON_DIR.glob("*.json"))
    if not archivos:
        print(f"❌ No hay archivos .json en {JSON_DIR}")
        sys.exit(1)
    for path in archivos:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for row in data:
            addr = row.get("address")
            if addr:
                addresses.add(addr.strip())
    print(f"📂 {len(archivos)} archivos JSON leídos")
    print(f"📍 {len(addresses)} addresses únicas encontradas")
    return sorted(addresses)


def main():
    parser = argparse.ArgumentParser(description="Geocodifica addresses (uso único).")
    parser.add_argument(
        "--refresh", action="store_true",
        help="Borra el cache existente y geocodifica todo desde cero.",
    )
    parser.add_argument(
        "--retry", action="store_true",
        help="Reintenta solo las que están como null en el cache.",
    )
    args = parser.parse_args()

    cache = {} if args.refresh else load_cache()
    addresses = collect_addresses()

    if args.refresh:
        pendientes = addresses
        print("🔄 Modo --refresh: se re-geocodifica todo")
    elif args.retry:
        pendientes = [a for a in addresses if cache.get(a) is None]
        print(f"🔁 Modo --retry: {len(pendientes)} fallidas anteriormente")
    else:
        pendientes = [a for a in addresses if a not in cache]
        print(f"➕ Direcciones nuevas a geocodificar: {len(pendientes)}")

    if not pendientes:
        print("✅ Nada que hacer. Cache ya está al día.")
        return

    estimado = len(pendientes) * REQUEST_DELAY_SEC
    print(f"⏱  Tiempo estimado mínimo: ~{estimado:.0f}s "
          f"({estimado / 60:.1f} min)\n")

    ok = 0
    fail = 0
    for i, addr in enumerate(pendientes, start=1):
        print(f"[{i}/{len(pendientes)}] {addr[:80]}{'...' if len(addr) > 80 else ''}")
        result = query_address(addr)
        if result is not None:
            cache[addr] = [result[0], result[1]]
            ok += 1
            print(f"   ✔ {result[0]:.5f}, {result[1]:.5f}")
        else:
            cache[addr] = None
            fail += 1
            print("   ✗ no encontrada")
        # Guardar progreso cada 10 (por si interrumpes con Ctrl+C)
        if i % 10 == 0:
            save_cache(cache)
        time.sleep(REQUEST_DELAY_SEC)

    save_cache(cache)
    print("\n────────────────────────────────")
    print(f"✅ Resueltas: {ok}")
    print(f"❌ Fallidas:  {fail}")
    print(f"💾 Guardado en: {CACHE_PATH}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠ Interrumpido. El progreso parcial quedó guardado.")
