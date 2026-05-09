"""
Smoke test del RappiScraper integrado:
3 zonas (Polanco, Lomas, San Jeronimo Monterrey) x 1 producto (Big Mac).
Valida: scraping individual + cambio de zona + cambio de ciudad + vaciado entre runs.
"""
import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv
from src.engine import launch_chrome_with_debug, run_platform

load_dotenv()


async def main():
    zones = [
        {
            "id": "cdmx_polanco",
            "city": "CDMX",
            "tier": "alto_alta",
            "address": "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX",
        },
        {
            "id": "cdmx_lomas",
            "city": "CDMX",
            "tier": "alto_baja",
            "address": "Av. Reforma 1500, Lomas de Chapultepec, Miguel Hidalgo, 11000 CDMX",
        },
        {
            "id": "mty_san_jeronimo",
            "city": "Monterrey",
            "tier": "alto_alta",
            "address": "Av. San Jeronimo 1000, San Jeronimo, Monterrey, 64640 NL",
        },
    ]

    products = json.loads(Path("config/products.json").read_text())["products"]
    big_mac = next(p for p in products if p["id"] == "big_mac")
    products_to_test = [big_mac]

    print("=== Smoke test Rappi ===")
    print(f"Zonas: {[z['id'] for z in zones]}")
    print(f"Productos: {[p['id'] for p in products_to_test]}")
    print()

    out_file = await run_platform("rappi", zones, products_to_test)
    print(f"\nResultado guardado en: {out_file}")

    data = json.loads(Path(out_file).read_text())
    print("\n=== Registros ===")
    for r in data:
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    print("Lanzando Chrome (cierra cualquier Chrome del proyecto antes)...")
    chrome = launch_chrome_with_debug()
    print(f"Chrome OK pid={chrome.pid}")
    try:
        asyncio.run(main())
    finally:
        chrome.terminate()
