import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from src.agent import discover_products_in_city
from src.engine import launch_chrome_with_debug, get_browser

load_dotenv()


async def grab_inventory(context, url: str, zone_address: str) -> list[str]:
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        text = await page.locator("body").inner_text()
        return text.split("\n")[:200]
    except Exception:
        return []
    finally:
        await page.close()


async def main():
    zones = json.loads(Path("config/zones.json").read_text())["zones"]
    cities = {}
    for z in zones:
        cities.setdefault(z["city"], z)

    chrome = launch_chrome_with_debug()
    try:
        pw, browser = await get_browser()
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()

        urls = {
            "rappi": "https://www.rappi.com.mx/",
            "uber": "https://www.ubereats.com/mx",
            "didi": "https://www.didi-food.com/es-MX/food/feed",
        }

        out = {}
        for city, zone in cities.items():
            inv = {}
            for plat, url in urls.items():
                inv[plat] = await grab_inventory(ctx, url, zone["address"])
                await asyncio.sleep(60)
            out[city] = discover_products_in_city(city, inv)

        Path("config/products_by_city.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
        await pw.stop()
    finally:
        chrome.terminate()


if __name__ == "__main__":
    asyncio.run(main())
