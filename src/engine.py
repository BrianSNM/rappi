"""
Engine de scraping competitivo: Rappi + DiDi Food (Uber descartado por ban).
Estrategia: paralelo escalonado con sincronizacion por zona.
Delays doblados respecto a version anterior.
"""
import asyncio
import json
import os
import random
import re
import socket
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, BrowserContext, Page

# ============================================================
# Configuracion - DELAYS DOBLADOS
# ============================================================
DELAY_PRODUCT = (30, 70)        # antes (15, 35)
DELAY_ZONE = (120, 240)         # antes (60, 120)
PLATFORM_OFFSET = {"rappi": 0, "didi": 60}  # Uber removido

PORTS = {"rappi": 9222, "didi": 9224}  # Uber descartado
PROFILE_DIRS = {p: Path(f"browser_profile_{p}").resolve() for p in PORTS}

SCREENSHOT_DIR = Path("data/screenshots")
RAW_DIR = Path("data/json")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)
for d in PROFILE_DIRS.values():
    d.mkdir(parents=True, exist_ok=True)


# ============================================================
# Chrome launcher
# ============================================================
def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def launch_chrome_for(platform: str) -> subprocess.Popen:
    binary = os.getenv("CHROME_BINARY", "/usr/bin/google-chrome")
    port = PORTS[platform]
    profile = PROFILE_DIRS[platform]
    proc = subprocess.Popen(
        [binary, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check",
         "--disable-notifications", "--disable-features=Translate,TranslateUI",
         "--disable-popup-blocking"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not _wait_for_port(port):
        proc.terminate()
        raise RuntimeError(f"Chrome {platform} no abrio puerto {port} en 15s")
    return proc


def launch_all_chromes() -> dict:
    procs = {}
    for platform in PORTS:
        procs[platform] = launch_chrome_for(platform)
        print(f"Chrome {platform} OK pid={procs[platform].pid} port={PORTS[platform]}")
    return procs


async def get_browser_for(platform: str):
    pw = await async_playwright().start()
    port = PORTS[platform]
    browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}")
    return pw, browser


# ============================================================
# Helpers
# ============================================================
def _parse_money(s: str) -> Optional[float]:
    if not s: return None
    cleaned = re.sub(r'[^\d,.]', '', s)
    if not cleaned: return None
    if '.' in cleaned and ',' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        if len(cleaned.split(',')[-1]) == 2:
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    try: return float(cleaned)
    except ValueError: return None


def _normalize_label(s: str) -> str:
    return s.rstrip(" .,;").lower().strip()


# ============================================================
# Clase abstracta
# ============================================================
class PlatformScraper(ABC):
    name: str
    home_url: str
    metric_patterns: dict
    eta_pattern: Optional[str] = None

    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Optional[Page] = None

    @abstractmethod
    async def back_to_home(self): ...
    @abstractmethod
    async def set_address(self, address: str): ...
    @abstractmethod
    async def add_product_to_cart(self, product: dict) -> bool: ...
    @abstractmethod
    async def go_to_checkout(self) -> str: ...
    @abstractmethod
    async def clear_cart(self): ...

    def extract_metrics(self, text: str) -> dict:
        out = {}
        for key, pat in self.metric_patterns.items():
            m = re.search(pat, text)
            out[key] = _parse_money(m.group(1)) if m else None
        if self.eta_pattern:
            m = re.search(self.eta_pattern, text)
            if m and len(m.groups()) == 2:
                out["eta_min"] = (int(m.group(1)) + int(m.group(2))) // 2
            elif m:
                out["eta_min"] = int(m.group(1))
            else:
                out["eta_min"] = None
        else:
            out["eta_min"] = None
        return out

    def _null_record(self, ts, zone, product, reason: str) -> dict:
        return {
            "ts": ts, "platform": self.name,
            "zone_id": zone["id"], "city": zone["city"], "tier": zone["tier"],
            "address": zone.get("address"),
            "product_id": product["id"], "merchant": product.get("merchant"),
            "subtotal": None, "delivery_fee": None, "service_fee": None, "eta_min": None,
            "error": reason,
        }

    async def scrape_product(self, zone: dict, product: dict) -> dict:
        ts = datetime.now().isoformat(timespec="minutes")
        try:
            added = await self.add_product_to_cart(product)
            if not added:
                try: await self.clear_cart()
                except Exception: pass
                return self._null_record(ts, zone, product, "not_available")

            checkout_text = await self.go_to_checkout()
            metrics = self.extract_metrics(checkout_text)

            shot_dir = SCREENSHOT_DIR / datetime.now().strftime("%Y%m%d_%H%M") / self.name
            shot_dir.mkdir(parents=True, exist_ok=True)
            try:
                await self.page.screenshot(
                    path=str(shot_dir / f"{zone['id']}_{product['id']}.png"),
                    full_page=False,
                )
            except Exception: pass

            await self.clear_cart()

            return {
                "ts": ts, "platform": self.name,
                "zone_id": zone["id"], "city": zone["city"], "tier": zone["tier"],
                "address": zone.get("address"),
                "product_id": product["id"], "merchant": product.get("merchant"),
                **metrics,
                "error": None,
            }
        except Exception as e:
            try: await self.clear_cart()
            except Exception: pass
            return self._null_record(ts, zone, product, f"error:{type(e).__name__}:{str(e)[:80]}")


# ============================================================
# RAPPI
# ============================================================
class RappiScraper(PlatformScraper):
    name = "rappi"
    home_url = "https://www.rappi.com.mx/"
    metric_patterns = {
        "subtotal":     r"Costo de productos[\s\n]*\$\s*([\d.,]+)",
        "delivery_fee": r"Costo de env[ií]o[\s\n]*\$\s*([\d.,]+)",
        "service_fee":  r"Tarifa de [Ss]ervicio[\s\n]*\$\s*([\d.,]+)",
    }
    eta_pattern = r"Entrega estimada:?\s*(\d+)\s*[-a]\s*(\d+)\s*min"

    async def _dismiss_cookies(self):
        try:
            b = self.page.locator('button:has-text("Ok, entendido")').first
            if await b.count() > 0 and await b.is_visible():
                await b.click(timeout=2000); await asyncio.sleep(0.5)
        except Exception: pass

    async def back_to_home(self):
        if self.page is None:
            self.page = await self.context.new_page()
        await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        await self._dismiss_cookies()

    async def set_address(self, address: str):
        await self.page.click('[data-qa="address-container"]', timeout=15000)
        await asyncio.sleep(2)
        await self.page.fill('[data-qa="address-input"]', address, timeout=15000)
        await asyncio.sleep(3)
        await self.page.locator('[data-qa="suggestion-item"]').first.click(timeout=10000)
        await asyncio.sleep(4)
        await self.page.locator('button:has-text("Confirmar")').first.click(timeout=10000)
        await asyncio.sleep(3)
        await self.page.locator('button:has-text("Guardar")').first.click(timeout=10000)
        await asyncio.sleep(4)

    async def add_product_to_cart(self, product: dict) -> bool:
        merchant_alt = product["merchant"]
        link = self.page.locator(
            f'a[href*="/restaurantes/delivery/"]:has(img[alt="{merchant_alt}"])'
        ).first
        if await link.count() == 0:
            return False
        await link.click(timeout=15000)
        await asyncio.sleep(6)

        await self.page.fill('[data-qa="input"]', product["label"], timeout=10000)
        await self.page.keyboard.press("Enter")
        await asyncio.sleep(4)

        target = None
        items = self.page.locator('[data-qa^="product-item-"]')
        norm_label = _normalize_label(product["label"])
        for i in range(await items.count()):
            item = items.nth(i)
            try:
                first_line = (await item.inner_text()).split("\n")[0].strip()
                if _normalize_label(first_line) == norm_label and await item.is_visible():
                    target = item; break
            except Exception: continue
        if target is None:
            return False

        await target.click(timeout=10000)
        await asyncio.sleep(3)
        try:
            await self.page.locator('button:has-text("Agregar")').first.click(timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(3)
        return True

    async def go_to_checkout(self) -> str:
        await self.page.locator('[data-qa="basket-icon"]').click(timeout=10000)
        await asyncio.sleep(3)
        await self.page.locator('[data-qa="go-to-pay-button"]').click(timeout=10000)
        await asyncio.sleep(5)
        try:
            antojo = self.page.locator('button:has-text("En otro momento")').first
            if await antojo.count() > 0 and await antojo.is_visible():
                await antojo.click(timeout=5000); await asyncio.sleep(3)
        except Exception: pass
        return await self.page.locator("body").inner_text()

    async def clear_cart(self):
        await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await self._dismiss_cookies()
        empty_p = self.page.locator('p:has-text("Vaciar todas las canastas")').first
        if await empty_p.count() == 0 or not await empty_p.is_visible():
            try:
                await self.page.locator('[data-qa="basket-icon"]').click(timeout=5000)
                await asyncio.sleep(2)
            except Exception: pass
        empty_p = self.page.locator('p:has-text("Vaciar todas las canastas")').first
        if await empty_p.count() > 0 and await empty_p.is_visible():
            await empty_p.click(timeout=5000); await asyncio.sleep(2)
            confirm = self.page.locator('button:has-text("seguro")').first
            if await confirm.count() > 0 and await confirm.is_visible():
                await confirm.click(timeout=5000); await asyncio.sleep(2)
        await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)


# ============================================================
# DIDI FOOD
# ============================================================
class DidiScraper(PlatformScraper):
    name = "didi"
    home_url = "https://www.didi-food.com/es-MX/food/"
    metric_patterns = {
        "subtotal":     r"Subtotal de los productos[\s\n]*MX\$?\s*([\d.,]+)",
        "delivery_fee": r"Tarifa de entrega[\s\n]*MX\$?\s*([\d.,]+)",
        "service_fee":  r"Tarifa de servicio[\s\n]*MX\$?\s*([\d.,]+)",
    }
    eta_pattern = r"(\d+)\s*[-a]\s*(\d+)\s*Min"

    async def back_to_home(self):
        if self.page is None:
            self.page = await self.context.new_page()
        await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(4)

    async def set_address(self, address: str):
        await self.page.locator('.poi-display-name').first.click(timeout=10000)
        await asyncio.sleep(3)
        filled = False
        for sel in ['.el-floating__body input.el-input__inner',
                    '.el-floating__body input',
                    'input[placeholder*="Ingresa una direcci" i]']:
            for el in await self.page.locator(sel).all():
                if await el.is_visible():
                    await el.fill(address, timeout=5000); filled = True; break
            if filled: break
        if not filled:
            raise Exception("No encontre input de direccion DiDi")
        await asyncio.sleep(3)
        sugs = await self.page.locator('.delivery-address__content').all()
        clicked = False
        for s in sugs:
            try:
                if not await s.is_visible(): continue
                await s.click(timeout=5000); clicked = True; break
            except Exception: continue
        if not clicked:
            raise Exception("No encontre sugerencia DiDi")
        await asyncio.sleep(6)

        try:
            oficina = self.page.locator('.infos-type_text:has-text("Oficina")').first
            if await oficina.count() == 0:
                oficina = self.page.locator('div:text-is("Oficina")').first
            if await oficina.count() > 0 and await oficina.is_visible():
                await oficina.click(timeout=5000); await asyncio.sleep(3)
                confirm = self.page.locator('button.el-button:has(span:text-is("Confirmar"))').first
                try: await confirm.scroll_into_view_if_needed(timeout=3000)
                except Exception: pass
                await asyncio.sleep(0.5)
                await confirm.click(timeout=5000, force=True)
                await asyncio.sleep(4)
                still = self.page.locator('button.el-button:has(span:text-is("Confirmar"))').first
                if await still.count() > 0 and await still.is_visible():
                    await still.click(timeout=5000, force=True); await asyncio.sleep(4)
        except Exception: pass

    async def add_product_to_cart(self, product: dict) -> bool:
        filled = False
        for sel in ['input[placeholder*="restaurantes" i]', 'input[placeholder*="comida" i]']:
            for el in await self.page.locator(sel).all():
                if await el.is_visible():
                    await el.fill("", timeout=5000)
                    await el.fill(product["merchant_search"], timeout=10000)
                    await self.page.keyboard.press("Enter"); filled = True; break
            if filled: break
        if not filled: return False
        await asyncio.sleep(6)

        merchant_keyword = product["merchant"].split("'")[0]
        target = None
        imgs = await self.page.locator(f'img[alt*="{merchant_keyword}" i]').all()
        for img in imgs[:5]:
            try:
                if not await img.is_visible(): continue
                parent = img.locator('xpath=ancestor::dl[contains(@class, "shop-card")][1]')
                if await parent.count() > 0:
                    target = parent.first; break
            except Exception: continue
        if target is None: return False
        await target.click(timeout=10000)
        await asyncio.sleep(6)

        target_item = None
        norm_label = _normalize_label(product["label"])
        max_scrolls = 12
        for scroll_i in range(max_scrolls):
            items = await self.page.locator('.item-card').all()
            for item in items:
                try:
                    if not await item.is_visible(): continue
                    first_line = (await item.inner_text()).split("\n")[0].strip()
                    if _normalize_label(first_line) == norm_label:
                        target_item = item; break
                except Exception: continue
            if target_item is not None: break
            bm = self.page.locator(f'text=/^{re.escape(product["label"])}$/i')
            for i in range(await bm.count()):
                el = bm.nth(i)
                try:
                    if await el.is_visible():
                        parent = el.locator('xpath=ancestor::*[contains(@class, "item-card")][1]')
                        if await parent.count() > 0:
                            target_item = parent.first; break
                except Exception: continue
            if target_item is not None: break
            await self.page.evaluate("window.scrollBy(0, 600)")
            await asyncio.sleep(1)
        if target_item is None: return False

        await target_item.locator('button:has-text("Agregar")').first.click(timeout=10000)
        await asyncio.sleep(3)

        try:
            add = self.page.locator('.add-btn').first
            await add.wait_for(state='visible', timeout=4000)
            await add.click(timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(3)
        return True

    async def go_to_checkout(self) -> str:
        await self.page.locator('button:has-text("Pagar")').first.click(timeout=10000)
        await asyncio.sleep(6)
        return await self.page.locator("body").inner_text()

    async def clear_cart(self):
        await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)
        try:
            vc = self.page.locator('button:has-text("Ver carrito"), a:has-text("Ver carrito")').first
            if await vc.count() > 0 and await vc.is_visible():
                await vc.click(timeout=5000); await asyncio.sleep(3)
        except Exception: return
        try:
            for sel in ['.cart-item-delete', '.icon-outlined_delete']:
                el = self.page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click(timeout=5000); break
            await asyncio.sleep(2)
        except Exception: pass
        try:
            await asyncio.sleep(1)
            confirm = self.page.locator('button.el-new-alert-highlight').first
            if await confirm.count() == 0 or not await confirm.is_visible():
                confirm = self.page.locator('button:has-text("Confirmar")').last
            await confirm.click(timeout=5000, force=True); await asyncio.sleep(3)
            still = self.page.locator('button.el-new-alert-highlight').first
            if await still.count() > 0 and await still.is_visible():
                await still.click(timeout=5000, force=True); await asyncio.sleep(3)
        except Exception: pass
        try:
            await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        except Exception: pass


SCRAPERS = {"rappi": RappiScraper, "didi": DidiScraper}


# ============================================================
# Worker por plataforma
# ============================================================
async def platform_worker(platform: str, zones: list, products: list, results: list,
                          run_ts: str):
    await asyncio.sleep(PLATFORM_OFFSET[platform])
    print(f"[{platform}] arrancando con offset {PLATFORM_OFFSET[platform]}s")

    out_file = RAW_DIR / f"{platform}_{run_ts}.json"

    pw, browser = await get_browser_for(platform)
    contexts = browser.contexts
    context = contexts[0] if contexts else await browser.new_context()

    scraper = SCRAPERS[platform](context)
    scraper.page = await context.new_page()

    try:
        for zi, zone in enumerate(zones):
            print(f"[{platform}] zona {zi+1}/{len(zones)}: {zone['id']} ({zone['address'][:60]})")

            try:
                await scraper.back_to_home()
                await scraper.set_address(zone["address"])
            except Exception as e:
                print(f"[{platform}] {zone['id']} ERROR direccion: {type(e).__name__}: {str(e)[:100]}")
                for product in products:
                    results.append(scraper._null_record(
                        datetime.now().isoformat(timespec="minutes"),
                        zone, product, f"address_failed:{type(e).__name__}"
                    ))
                _save_partial(out_file, results)
                await asyncio.sleep(random.uniform(*DELAY_ZONE))
                continue

            for pi, product in enumerate(products):
                rec = await scraper.scrape_product(zone, product)
                results.append(rec)
                print(f"[{platform}] {zone['id']} {product['id']}: "
                      f"sub={rec.get('subtotal')} del={rec.get('delivery_fee')} "
                      f"svc={rec.get('service_fee')} eta={rec.get('eta_min')} "
                      f"err={rec.get('error')}")
                if pi < len(products) - 1:
                    d = random.uniform(*DELAY_PRODUCT)
                    await asyncio.sleep(d)

            _save_partial(out_file, results)

            d = random.uniform(*DELAY_ZONE)
            print(f"[{platform}] descanso {d:.0f}s antes de zona siguiente")
            await asyncio.sleep(d)
    finally:
        try: await scraper.page.close()
        except Exception: pass
        try: await pw.stop()
        except Exception: pass

    print(f"[{platform}] terminado: {len(results)} registros en {out_file}")


def _save_partial(out_file: Path, records: list):
    try:
        out_file.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[!] Error guardando {out_file}: {e}")


# ============================================================
# Orquestador
# ============================================================
async def run_all(zones_path="config/zones.json", products_path="config/products.json"):
    zones = json.loads(Path(zones_path).read_text())["zones"]
    products = json.loads(Path(products_path).read_text())["products"]

    run_ts = datetime.now().strftime("%Y%m%d_%H%M")

    print(f"=== Corrida competitiva (Rappi + DiDi) ===")
    print(f"Zonas: {len(zones)}, Productos: {len(products)}, Plataformas: {list(PORTS)}")
    print(f"Delays: producto={DELAY_PRODUCT}s, zona={DELAY_ZONE}s, offset={PLATFORM_OFFSET}")
    print(f"Output: {RAW_DIR}/<plataforma>_{run_ts}.json")
    print(f"Sin limite de tiempo - corre hasta completar las {len(zones)} zonas")

    results_by_platform = {p: [] for p in PORTS}

    tasks = [
        platform_worker(p, zones, products, results_by_platform[p], run_ts)
        for p in PORTS
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    out_files = []
    for p, recs in results_by_platform.items():
        f = RAW_DIR / f"{p}_{run_ts}.json"
        f.write_text(json.dumps(recs, ensure_ascii=False, indent=2))
        print(f"[{p}] guardado: {f} ({len(recs)} registros)")
        out_files.append(str(f))

    return out_files
