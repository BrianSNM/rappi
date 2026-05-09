"""
Test Rappi con los 3 productos en 1 zona (Polanco).
Recorre Big Mac (McDonald's) -> Boneless Bites (Subway) -> Queso (Little Caesars).
"""
import asyncio
import json
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright, Page

ZONE = {"id": "cdmx_polanco", "address": "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"}
HOME_URL = "https://www.rappi.com.mx/"
SHOTS = "data/screenshots/rappi_3prod"
os.makedirs(SHOTS, exist_ok=True)

PRODUCTS = json.loads(Path("config/products.json").read_text())["products"]


def parse_money(s):
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


def extract_metrics(text):
    metrics = {}
    patterns = {
        "subtotal":     r"Costo de productos[\s\n]*\$\s*([\d.,]+)",
        "delivery_fee": r"Costo de env[ií]o[\s\n]*\$\s*([\d.,]+)",
        "service_fee":  r"Tarifa de [Ss]ervicio[\s\n]*\$\s*([\d.,]+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        metrics[key] = parse_money(m.group(1)) if m else None
    return metrics


async def step(page, name, fn):
    print(f"\n  >>> {name}")
    input("      [ENTER]")
    try:
        await fn()
        print(f"      OK")
        return True
    except Exception as e:
        shot = f"{SHOTS}/FAIL_{name[:20].replace(' ','_').replace('/','_')}.png"
        try:
            await page.screenshot(path=shot, full_page=False)
            print(f"      FAIL: {type(e).__name__}: {str(e)[:200]}")
            print(f"      Screenshot: {shot}")
        except Exception: pass
        return False


async def dismiss_cookies(page):
    try:
        b = page.locator('button:has-text("Ok, entendido")').first
        if await b.count() > 0 and await b.is_visible():
            await b.click(timeout=2000); await asyncio.sleep(0.5)
    except Exception: pass


async def setup_address(page):
    """Solo se hace una vez al inicio."""
    print("\n=== SETUP DIRECCION ===")

    if not await step(page, "Cargar rappi.com.mx",
        lambda: page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)): return False
    await asyncio.sleep(3)
    await dismiss_cookies(page)

    if not await step(page, "Click address-container",
        lambda: page.click('[data-qa="address-container"]', timeout=15000)): return False
    await asyncio.sleep(2)

    if not await step(page, "Llenar address-input",
        lambda: page.fill('[data-qa="address-input"]', ZONE["address"], timeout=15000)): return False
    await asyncio.sleep(3)

    if not await step(page, "Click suggestion-item",
        lambda: page.locator('[data-qa="suggestion-item"]').first.click(timeout=10000)): return False
    await asyncio.sleep(4)

    if not await step(page, "Click Confirmar",
        lambda: page.locator('button:has-text("Confirmar")').first.click(timeout=10000)): return False
    await asyncio.sleep(3)

    if not await step(page, "Click Guardar",
        lambda: page.locator('button:has-text("Guardar")').first.click(timeout=10000)): return False
    await asyncio.sleep(4)

    return True


async def scrape_product(page, product):
    """Para cada producto."""
    print(f"\n=== PRODUCTO: {product['id']} ({product['merchant']} / {product['label']}) ===")

    # 1. Click merchant via "10 mas elegidos" (a[href*="/restaurantes/delivery/"])
    print(f"\n  >>> Buscar '{product['merchant']}' en 10 mas elegidos")
    input("      [ENTER]")
    try:
        link = page.locator(
            f'a[href*="/restaurantes/delivery/"]:has(img[alt="{product["merchant"]}"])'
        ).first
        if await link.count() == 0:
            print(f"      [!] No encontre {product['merchant']} en '10 mas elegidos'")
            return None
        await link.click(timeout=15000)
        print("      OK click merchant")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(6)
    print(f"      URL: {page.url}")

    # 2. Buscador interno
    print(f"\n  >>> Buscar '{product['label']}' en buscador interno")
    input("      [ENTER]")
    try:
        await page.fill('[data-qa="input"]', product["label"], timeout=10000)
        await page.keyboard.press("Enter")
        print("      OK busqueda enviada")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(4)

    # 3. Buscar product-item exacto
    print(f"\n  >>> Buscar product-item con titulo exacto '{product['label']}'")
    target_item = None
    items = page.locator('[data-qa^="product-item-"]')
    cnt = await items.count()
    print(f"      Total product-items: {cnt}")
    for i in range(cnt):
        try:
            item = items.nth(i)
            first_line = (await item.inner_text()).split("\n")[0].strip()
            visible = await item.is_visible()
            if i < 5:
                print(f"      [{i}] visible={visible} primera_linea='{first_line}'")
            # Normalizar: quitar puntuacion final, lowercase, comparar
            norm_first = first_line.rstrip(" .,;").lower().strip()
            norm_label = product["label"].rstrip(" .,;").lower().strip()
            if norm_first == norm_label and visible and target_item is None:
                target_item = item
                print(f"        >> MATCH (normalizado)")
        except Exception: continue

    if target_item is None:
        print(f"      [!] No encontre exacto. Coincidencias parciales:")
        bm = page.locator(f'text=/{re.escape(product["label"])}/i')
        scnt = await bm.count()
        for i in range(min(scnt, 5)):
            try:
                t = (await bm.nth(i).inner_text())[:80].replace("\n", " ")
                print(f"        [{i}] '{t}'")
            except Exception: pass
        return None

    print(f"\n  >>> Click product-item")
    input("      [ENTER]")
    try:
        await target_item.click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(3)

    # 4. Modal del producto -> "Agregar" (botón verde)
    print(f"\n  >>> Esperar modal y click 'Agregar' (boton verde)")
    input("      [ENTER]")
    try:
        # Esperar a que el modal aparezca
        await page.wait_for_selector(f'[data-qa="modal-header"]:has-text("{product["label"]}")', timeout=8000)
        print("      Modal detectado")
        await page.locator('button:has-text("Agregar")').first.click(timeout=10000)
        print("      OK Agregar")
    except Exception as e:
        print(f"      [!] Modal no aparecio o fallo click: {e}")
        # Fallback: producto sin personalizacion (igual que DiDi/Queso): se agrega directo
        print("      Fallback: asumir agregado directo, continuar")
    await asyncio.sleep(3)

    # 5. Click basket-icon (abrir panel carrito)
    print(f"\n  >>> Click basket-icon")
    input("      [ENTER]")
    try:
        await page.locator('[data-qa="basket-icon"]').click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(3)

    # 6. Click "Ir a pagar"
    print(f"\n  >>> Click 'Ir a pagar' (data-qa=go-to-pay-button)")
    input("      [ENTER]")
    try:
        await page.locator('[data-qa="go-to-pay-button"]').click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(5)

    # 7. Modal "Antojo" -> "En otro momento"
    print(f"\n  >>> Cerrar modal antojo (En otro momento) si aparece")
    try:
        antojo = page.locator('button:has-text("En otro momento")').first
        if await antojo.count() > 0 and await antojo.is_visible():
            await antojo.click(timeout=5000); print("      OK"); await asyncio.sleep(3)
        else:
            print("      Sin modal antojo")
    except Exception as e:
        print(f"      Error: {e}")

    # 8. Capturar metricas
    print(f"\n  >>> Capturar metricas")
    await asyncio.sleep(2)
    await page.screenshot(path=f"{SHOTS}/{product['id']}_checkout.png", full_page=True)
    text = await page.locator("body").inner_text()
    metrics = extract_metrics(text)
    print(f"      Metricas: {metrics}")

    # 9. Vaciar carrito (volver a home + abrir panel + Vaciar todas las canastas + Si seguro)
    print(f"\n  >>> Vaciar carrito")
    input("      [ENTER]")
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await dismiss_cookies(page)

        # Ver si el panel ya esta abierto (a veces se abre solo)
        empty_p = page.locator('p:has-text("Vaciar todas las canastas")').first
        if await empty_p.count() == 0 or not await empty_p.is_visible():
            try:
                await page.locator('[data-qa="basket-icon"]').click(timeout=5000)
                await asyncio.sleep(2)
            except Exception: pass

        empty_p = page.locator('p:has-text("Vaciar todas las canastas")').first
        if await empty_p.count() > 0 and await empty_p.is_visible():
            await empty_p.click(timeout=5000)
            await asyncio.sleep(2)
            confirm = page.locator('button:has-text("seguro")').first
            if await confirm.count() > 0 and await confirm.is_visible():
                await confirm.click(timeout=5000); await asyncio.sleep(2)
                print("      OK carrito vaciado")
            else:
                print("      [!] No encontre 'Si seguro'")
        else:
            print("      Carrito ya vacio o boton no visible")

        # Volver a home limpio
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
    except Exception as e:
        print(f"      Error vaciado: {e}")

    return metrics


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
    ctx = browser.contexts[0]

    print(f"Limpiando pestanas viejas (hay {len(ctx.pages)})")
    for p in list(ctx.pages):
        try:
            if p.url and "rappi" in p.url:
                await p.close()
        except Exception: pass

    page = await ctx.new_page()

    if not await setup_address(page):
        print("\n[!] Setup direccion fallo. Abortando.")
        return

    results = {}
    for product in PRODUCTS:
        try:
            metrics = await scrape_product(page, product)
            results[product["id"]] = metrics
        except Exception as e:
            print(f"\n[!] Error global con {product['id']}: {e}")
            results[product["id"]] = None

    print(f"\n{'='*60}")
    print(f"=== RESUMEN ===")
    for pid, m in results.items():
        print(f"  {pid}: {m}")


if __name__ == "__main__":
    asyncio.run(main())
