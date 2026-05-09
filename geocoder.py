"""
Geocodificación de addresses → (lat, lon) con cache en disco.

Usa Nominatim (OpenStreetMap), gratis y sin API key.
Política de uso: máximo 1 request/segundo y User-Agent identificable.
https://operations.osmfoundation.org/policies/nominatim/

La primera vez que se ejecuta tarda ~1 seg por dirección única.
Resultados se guardan en data/geocache.json y reutilizan en siguientes ejecuciones.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "rappi-intel/1.0 (internal-tool)"
REQUEST_DELAY_SEC = 1.1  # respetar política de Nominatim


def _nominatim_one(query: str, timeout: int = 10) -> Optional[tuple[float, float]]:
    """Una consulta a Nominatim. Devuelve (lat, lon) o None."""
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
    Genera variantes de consulta cada vez más generales.
    Útil cuando Nominatim no encuentra la dirección exacta pero sí la calle o colonia.

    Ejemplo:
      "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"
      → ["Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX",
         "Av. Presidente Masaryk, Polanco, Miguel Hidalgo, CDMX",
         "Polanco, Miguel Hidalgo, CDMX",
         "Miguel Hidalgo, CDMX",
         "CDMX"]
    """
    queries = [address]
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 2:
        # Sin la primera parte (calle+número) — solo barrio/alcaldía/ciudad
        queries.append(", ".join(parts[1:]))
    if len(parts) >= 3:
        queries.append(", ".join(parts[-3:]))
    if len(parts) >= 2:
        queries.append(", ".join(parts[-2:]))
    if parts:
        queries.append(parts[-1])
    # Quitar duplicados manteniendo orden
    seen = set()
    out = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _query_nominatim(address: str, timeout: int = 10) -> Optional[tuple[float, float]]:
    """Consulta con fallback progresivo. Respeta delay entre intentos."""
    queries = _build_fallback_queries(address)
    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(REQUEST_DELAY_SEC)
        result = _nominatim_one(q, timeout=timeout)
        if result is not None:
            return result
    return None


def load_cache(cache_path: Path) -> dict[str, list[float]]:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(cache: dict[str, list[float]], cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def geocode_addresses(
    addresses: list[str],
    cache_path: Path,
    progress_callback=None,
) -> dict[str, tuple[float, float]]:
    """
    Resuelve una lista de addresses a (lat, lon).

    - Lee el cache existente (no vuelve a consultar lo ya conocido).
    - Consulta Nominatim solo para las nuevas.
    - Guarda el cache actualizado al terminar.
    - Direcciones que no se pueden resolver no aparecen en el dict de salida.

    progress_callback: fn(i, total, address) opcional para UI de progreso.
    """
    cache = load_cache(cache_path)
    unique = list(dict.fromkeys(addresses))  # preserva orden, sin duplicados
    pendientes = [a for a in unique if a not in cache]

    for i, addr in enumerate(pendientes, start=1):
        if progress_callback:
            progress_callback(i, len(pendientes), addr)
        result = _query_nominatim(addr)
        if result is not None:
            cache[addr] = [result[0], result[1]]
        else:
            cache[addr] = None  # marcamos como intentado pero no resuelto
        time.sleep(REQUEST_DELAY_SEC)

    if pendientes:
        save_cache(cache, cache_path)

    return {
        addr: (coords[0], coords[1])
        for addr, coords in cache.items()
        if coords is not None and addr in unique
    }
