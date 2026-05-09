"""
Test Uber Eats con los 3 productos en 1 zona (Polanco).
Recorre Big Mac -> Boneless Bites -> Queso.
Despues de cada producto: capturar metricas y vaciar carrito.
"""
import asyncio
import json
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright, Page

ZONE = {"id": "cdmx_polanco", "address": "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"}
SHOTS = "data/screenshots/uber_3prod"
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
        "subtotal":     r"Subtotal[\s\n]*\$\s*([\d.,]+)",
        "delivery_fee": r"Costo de env[ií]o[\s\n]*\$\s*([\d.,]+)",
        "service_fee":  r"Cuota de servicio[\s\n]*\$\s*([\d.,]+)",
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


async def setup_address(page):
    """Solo se hace una vez al inicio."""
    print("\n=== SETUP DIRECCION ===")

    if not await step(page, "Cargar ubereats.com/mx",
        lambda: page.goto("https://www.ubereats.com/mx", wait_until="domcontentloaded", timeout=60000)): return False
    await asyncio.sleep(3)

    if not await step(page, "Click boton direccion",
        lambda: page.locator('[data-testid*="address" i]').first.click(timeout=15000)): return False
    await asyncio.sleep(3)

    print("\n  >>> Llenar input direccion")
    input("      [ENTER]")
    filled = False
    for el in await page.locator('input[placeholder*="busca" i]').all():
        if await el.is_visible():
            await el.fill(ZONE["address"], timeout=10000); filled = True; break
    if not filled:
        print("      FAIL: no encontre input visible")
        return False
    print("      OK")
    await asyncio.sleep(3)

    if not await step(page, "Click sugerencia",
        lambda: page.locator('li[role="option"]').first.click(timeout=10000)): return False
    await asyncio.sleep(4)

    print("\n  >>> Modal 'Elige tu edificio' -> Omitir (si aparece)")
    try:
        o = page.locator('button:has-text("Omitir")').first
        if await o.count() > 0 and await o.is_visible():
            await o.click(timeout=5000); print("      OK 'Omitir'"); await asyncio.sleep(3)
        else:
            print("      Sin modal")
    except Exception as e:
        print(f"      Error: {e}")

    print("\n  >>> Modal 'Informacion direccion' -> Guardar (si aparece)")
    try:
        g = page.locator('button:has-text("Guardar")').first
        if await g.count() > 0 and await g.is_visible():
            await g.click(timeout=5000); print("      OK 'Guardar'"); await asyncio.sleep(4)
        else:
            print("      Sin modal")
    except Exception as e:
        print(f"      Error: {e}")

    return True


async def scrape_product(page, product):
    """Para cada producto: buscar merchant -> click tienda -> producto -> agregar -> checkout -> capturar -> vaciar."""
    print(f"\n=== PRODUCTO: {product['id']} ({product['merchant']} / {product['label']}) ===")

    # 1. Buscar merchant en header
    print(f"\n  >>> Buscar merchant '{product['merchant_search']}' en header")
    input("      [ENTER]")
    try:
        filled = False
        for el in await page.locator('input[placeholder*="Buscar" i]').all():
            if await el.is_visible():
                await el.fill("", timeout=5000)  # limpiar antes
                await el.fill(product["merchant_search"], timeout=10000)
                await page.keyboard.press("Enter")
                filled = True
                break
        if not filled:
            print("      FAIL: no encontre buscador del header")
            return None
        print("      OK busqueda enviada")
    except Exception as e:
        print(f"      FAIL: {e}")
        return None
    await asyncio.sleep(8)
    try:
        await page.wait_for_selector('[data-testid="store-card"]', timeout=15000)
    except Exception:
        print("      [!] Timeout esperando store-cards")
        return None

    # 2. Inspeccionar y filtrar store-cards
    print(f"\n  >>> Inspeccionar store-cards (descartar 'Patrocinado')")
    cards = await page.locator('[data-testid="store-card"]').all()
    print(f"      Total store-cards: {len(cards)}")
    target_card = None
    merchant_keyword = product["merchant"].split("'")[0]  # "McDonald" / "Subway" / "Little Caesars"
    for i, c in enumerate(cards[:6]):
        try:
            text = (await c.inner_text())[:200].replace("\n", " | ")
            visible = await c.is_visible()
            is_ad = "Patrocinado" in text
            has_merchant = merchant_keyword.lower() in text.lower()
            print(f"      [{i}] visible={visible} ad={is_ad} merchant={has_merchant} text='{text[:100]}'")
            if not is_ad and has_merchant and target_card is None:
                target_card = c
                print(f"        >> SELECCIONADO")
        except Exception: pass

    if target_card is None:
        print(f"      [!] No encontre store-card de '{merchant_keyword}'")
        return None

    print(f"\n  >>> Click store-card de {merchant_keyword}")
    input("      [ENTER]")
    try:
        await target_card.click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}")
        return None
    await asyncio.sleep(6)

    # 3. (omitido) Buscador interno - causa problemas, mejor scroll natural
    # 4. Click producto exacto (busqueda directa en menu visible)
    print(f"\n  >>> Buscar texto exacto '{product['label']}'")
    bm = page.locator(f'text=/^{re.escape(product["label"])}$/')
    cnt = await bm.count()
    print(f"      Total exactos: {cnt}")
    if cnt == 0:
        print(f"      Buscando con contains...")
        bm = page.locator(f'text=/{re.escape(product["label"])}/i')
        cnt = await bm.count()
        print(f"      Total contiene: {cnt}")

    target = None
    for i in range(min(cnt, 5)):
        el = bm.nth(i)
        try:
            text = (await el.inner_text())[:60].replace("\n", " ")
            visible = await el.is_visible()
            print(f"      [{i}] visible={visible} text='{text}'")
            if visible and target is None:
                target = el
        except Exception: pass

    if target is None:
        print(f"      [!] No encontre el producto visible")
        return None

    print(f"\n  >>> Click en producto")
    input("      [ENTER]")
    try:
        await target.click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}")
        return None
    await asyncio.sleep(3)

    # 5. Modal del producto -> Agregar
    print(f"\n  >>> Click 'Agregar X al pedido' en modal")
    input("      [ENTER]")
    try:
        await page.locator('button:has-text("Agregar")').filter(
            has_text=re.compile("pedido|al pedido", re.I)
        ).first.click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}")
        return None
    await asyncio.sleep(3)

    # 6. Pop-up "Continuar" (rapido, sin ENTER intermedio)
    print(f"\n  >>> Click 'Continuar' del pop-up (automatico, dura 2s)")
    await asyncio.sleep(0.8)
    try:
        cont = page.locator('button:has-text("Continuar")').first
        await cont.click(timeout=3000)
        print("      OK")
    except Exception as e:
        print(f"      Pop-up no disponible: {e}")
        try:
            cart = page.locator('[data-testid*="cart" i], a[href*="cart"]').first
            await cart.click(timeout=5000); await asyncio.sleep(2)
            cont = page.locator('button:has-text("Continuar")').first
            await cont.click(timeout=5000)
            print("      OK fallback carrito")
        except Exception as e2:
            print(f"      FAIL fallback: {e2}")
            return None
    await asyncio.sleep(5)

    # 7. Modal Omitir
    print(f"\n  >>> Modal 'Completa tu pedido' -> Omitir (si aparece)")
    try:
        o = page.locator('button:has-text("Omitir")').first
        if await o.count() > 0 and await o.is_visible():
            await o.click(timeout=5000); print("      OK"); await asyncio.sleep(3)
        else:
            print("      Sin modal")
    except Exception as e:
        print(f"      Error: {e}")

    # 8. Capturar metricas
    print(f"\n  >>> Capturar metricas")
    await asyncio.sleep(2)
    await page.screenshot(path=f"{SHOTS}/{product['id']}_checkout.png", full_page=True)
    text = await page.locator("body").inner_text()
    metrics = extract_metrics(text)
    print(f"      Metricas: {metrics}")

    # 9. Vaciar carrito (volver home + abrir carrito + papelera)
    print(f"\n  >>> Vaciar carrito")
    input("      [ENTER]")
    try:
        await page.goto("https://www.ubereats.com/mx", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        cart_btn = None
        for sel in ['[data-testid="topnav-cart-button"]', 'button[aria-label*="carrito" i]',
                    'button[aria-label*="cart" i]', 'a[href*="cart"]']:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                cart_btn = el; break
        if cart_btn:
            await cart_btn.click(timeout=5000)
            await asyncio.sleep(2)
            trash = page.locator('button[data-test="item-stepper-dec"]').first
            if await trash.count() > 0:
                await trash.click(timeout=5000)
                await asyncio.sleep(3)
                print("      OK papelera")
            else:
                print("      [!] No encontre papelera")
        else:
            print("      [!] No encontre boton de carrito")
        await page.goto("https://www.ubereats.com/mx", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
    except Exception as e:
        print(f"      Error vaciado: {e}")

    return metrics


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp("http://localhost:9223")
    ctx = browser.contexts[0]

    print(f"Limpiando pestanas viejas (hay {len(ctx.pages)})")
    for p in list(ctx.pages):
        try:
            if p.url and "ubereats" in p.url:
                await p.close()
        except Exception: pass

    page = await ctx.new_page()

    # Setup direccion una sola vez
    if not await setup_address(page):
        print("\n[!] Setup de direccion fallo. Abortando.")
        return

    # Recorrer los 3 productos
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
