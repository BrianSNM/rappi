"""
Test DiDi Food con los 3 productos en 1 zona (Polanco).
Recorre Big Mac (McDonald's) -> Boneless Bites (Subway) -> Queso (Little Caesars).
"""
import asyncio
import json
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright, Page

ZONE = {"id": "cdmx_polanco", "address": "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"}
HOME_URL = "https://www.didi-food.com/es-MX/food/"
SHOTS = "data/screenshots/didi_3prod"
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
        "subtotal":     r"Subtotal de los productos[\s\n]*MX\$?\s*([\d.,]+)",
        "delivery_fee": r"Tarifa de entrega[\s\n]*MX\$?\s*([\d.,]+)",
        "service_fee":  r"Tarifa de servicio[\s\n]*MX\$?\s*([\d.,]+)",
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

    if not await step(page, "Cargar didi-food.com",
        lambda: page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)): return False
    await asyncio.sleep(4)

    if not await step(page, "Click direccion (.poi-display-name)",
        lambda: page.locator('.poi-display-name').first.click(timeout=10000)): return False
    await asyncio.sleep(3)

    print("\n  >>> Llenar input direccion (modal floating)")
    input("      [ENTER]")
    filled = False
    for sel in ['.el-floating__body input.el-input__inner',
                '.el-floating__body input',
                'input[placeholder*="Ingresa una direcci" i]']:
        for el in await page.locator(sel).all():
            if await el.is_visible():
                await el.fill(ZONE["address"], timeout=5000); filled = True; break
        if filled: break
    if not filled:
        print("      FAIL: no encontre input"); return False
    print("      OK")
    await asyncio.sleep(3)

    print("\n  >>> Click primera sugerencia (.delivery-address__content)")
    input("      [ENTER]")
    try:
        sugs = await page.locator('.delivery-address__content').all()
        clicked = False
        for s in sugs:
            if await s.is_visible():
                await s.click(timeout=5000); clicked = True; break
        if not clicked:
            print("      FAIL: ninguna sugerencia visible"); return False
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}"); return False
    await asyncio.sleep(6)

    print("\n  >>> Modal 'Direccion de entrega' -> Oficina + Confirmar (con 2do click)")
    try:
        oficina = page.locator('.infos-type_text:has-text("Oficina")').first
        if await oficina.count() == 0:
            oficina = page.locator('div:text-is("Oficina")').first
        if await oficina.count() > 0 and await oficina.is_visible():
            await oficina.click(timeout=5000); print("      OK Oficina"); await asyncio.sleep(3)
            confirm = page.locator('button.el-button:has(span:text-is("Confirmar"))').first
            try: await confirm.scroll_into_view_if_needed(timeout=3000)
            except Exception: pass
            await asyncio.sleep(0.5)
            await confirm.click(timeout=5000, force=True)
            print("      OK Confirmar (1er click)")
            await asyncio.sleep(4)
            still = page.locator('button.el-button:has(span:text-is("Confirmar"))').first
            if await still.count() > 0 and await still.is_visible():
                await still.click(timeout=5000, force=True)
                print("      OK Confirmar (2do click)")
                await asyncio.sleep(4)
        else:
            print("      Sin modal de tipo de ubicacion")
    except Exception as e:
        print(f"      Error en modal direccion: {e}")

    return True


async def scrape_product(page, product):
    """Para cada producto."""
    print(f"\n=== PRODUCTO: {product['id']} ({product['merchant']} / {product['label']}) ===")

    # 1. Buscar merchant en header
    print(f"\n  >>> Buscar merchant '{product['merchant_search']}' en header")
    input("      [ENTER]")
    try:
        filled = False
        for sel in ['input[placeholder*="restaurantes" i]', 'input[placeholder*="comida" i]']:
            for el in await page.locator(sel).all():
                if await el.is_visible():
                    await el.fill("", timeout=5000)
                    await el.fill(product["merchant_search"], timeout=10000)
                    await page.keyboard.press("Enter")
                    filled = True; break
            if filled: break
        if not filled:
            print("      FAIL: no encontre buscador del header"); return None
        print("      OK busqueda enviada")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(6)

    # 2. Inspeccionar tarjetas y elegir la primera del merchant
    print(f"\n  >>> Inspeccionar tarjetas con img alt='{product['merchant']}'")
    merchant_keyword = product["merchant"].split("'")[0]  # "McDonald" / "Subway" / "Little Caesars"
    target = None
    imgs = await page.locator(f'img[alt*="{merchant_keyword}" i]').all()
    print(f"      Imgs con alt='{merchant_keyword}': {len(imgs)}")
    for i, img in enumerate(imgs[:5]):
        try:
            visible = await img.is_visible()
            alt = await img.get_attribute("alt")
            print(f"      [{i}] visible={visible} alt='{alt}'")
            if not visible: continue
            # El clickable es <dl class="shop-card"> ancestor de la img
            parent = img.locator('xpath=ancestor::dl[contains(@class, "shop-card")][1]')
            if await parent.count() > 0 and target is None:
                target = parent.first
                print(f"        >> SELECCIONADO (dl.shop-card)")
                break
        except Exception as e:
            print(f"      [{i}] error: {e}")

    if target is None:
        print(f"      [!] No encontre tarjeta clickable de '{merchant_keyword}'")
        return None

    print(f"\n  >>> Click tarjeta")
    input("      [ENTER]")
    try:
        await target.click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(6)
    print(f"      URL: {page.url}")

    # 3. Buscar producto exacto con scroll progresivo (sin buscador interno)
    print(f"\n  >>> Buscar '{product['label']}' con scroll progresivo")
    target_item = None
    max_scrolls = 12
    for scroll_i in range(max_scrolls):
        # Estrategia 1: .item-card cuyo primer renglon sea exacto
        items = await page.locator('.item-card').all()
        for item in items:
            try:
                if not await item.is_visible(): continue
                first_line = (await item.inner_text()).split("\n")[0].strip()
                if first_line == product["label"]:
                    target_item = item
                    break
            except Exception: continue
        if target_item is not None:
            print(f"      OK encontrado tras {scroll_i} scrolls")
            break
        # Estrategia 2 fallback: text exacto y ancestor item-card
        bm = page.locator(f'text=/^{re.escape(product["label"])}$/i')
        for i in range(await bm.count()):
            el = bm.nth(i)
            try:
                if await el.is_visible():
                    parent = el.locator('xpath=ancestor::*[contains(@class, "item-card")][1]')
                    if await parent.count() > 0:
                        target_item = parent.first
                        break
            except Exception: continue
        if target_item is not None:
            print(f"      OK encontrado via fallback tras {scroll_i} scrolls")
            break
        await page.evaluate("window.scrollBy(0, 600)")
        await asyncio.sleep(1)

    if target_item is None:
        print(f"      [!] No encontre '{product['label']}' tras {max_scrolls} scrolls")
        # Diagnostico
        similar = page.locator(f'text=/{re.escape(product["label"])}/i')
        scnt = await similar.count()
        print(f"      Coincidencias parciales: {scnt}")
        for i in range(min(scnt, 5)):
            try:
                t = (await similar.nth(i).inner_text())[:80].replace("\n", " ")
                print(f"        [{i}] '{t}'")
            except Exception: pass
        return None

    # 4. Click "Agregar" dentro de la tarjeta
    print(f"\n  >>> Click 'Agregar' en la tarjeta")
    input("      [ENTER]")
    try:
        await target_item.locator('button:has-text("Agregar")').first.click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(3)

    # 5. Modal del producto -> .add-btn (solo si aparece; algunos productos simples se agregan directo al carrito)
    print(f"\n  >>> Esperar modal del producto (.add-btn) si aparece")
    await asyncio.sleep(2)
    try:
        add = page.locator('.add-btn').first
        # Esperar hasta 4s a que aparezca el modal
        try:
            await add.wait_for(state='visible', timeout=4000)
            await add.click(timeout=5000)
            print("      OK modal abierto + click .add-btn")
        except Exception:
            # Modal no aparecio: el producto ya se agrego directo al carrito
            print("      Sin modal: producto agregado directo al carrito (simple, sin personalizacion)")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(3)

    # 6. Pop-up "Pagar" (queda permanente)
    print(f"\n  >>> Click 'Pagar' del pop-up mini-cart")
    input("      [ENTER]")
    try:
        await page.locator('button:has-text("Pagar")').first.click(timeout=10000)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}"); return None
    await asyncio.sleep(6)

    # 7. Capturar metricas
    print(f"\n  >>> Capturar metricas")
    await page.screenshot(path=f"{SHOTS}/{product['id']}_checkout.png", full_page=True)
    text = await page.locator("body").inner_text()
    metrics = extract_metrics(text)
    print(f"      Metricas: {metrics}")

    # 8. Vaciar carrito
    print(f"\n  >>> Vaciar carrito")
    input("      [ENTER]")
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)
        # Click "Ver carrito"
        vc = page.locator('button:has-text("Ver carrito"), a:has-text("Ver carrito")').first
        if await vc.count() > 0 and await vc.is_visible():
            await vc.click(timeout=5000); await asyncio.sleep(3)
        # Papelera
        for sel in ['.cart-item-delete', '.icon-outlined_delete']:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.click(timeout=5000); break
        await asyncio.sleep(2)
        # Confirmar (con posible 2do click)
        await asyncio.sleep(1)
        confirm = page.locator('button.el-new-alert-highlight').first
        if await confirm.count() == 0 or not await confirm.is_visible():
            confirm = page.locator('button:has-text("Confirmar")').last
        await confirm.click(timeout=5000, force=True)
        print("      OK Confirmar (1er click)")
        await asyncio.sleep(3)
        still = page.locator('button.el-new-alert-highlight').first
        if await still.count() > 0 and await still.is_visible():
            await still.click(timeout=5000, force=True)
            print("      OK Confirmar (2do click)")
            await asyncio.sleep(3)
        # Volver al home
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
    except Exception as e:
        print(f"      Error vaciado: {e}")

    return metrics


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp("http://localhost:9224")
    ctx = browser.contexts[0]

    print(f"Limpiando pestanas viejas (hay {len(ctx.pages)})")
    for p in list(ctx.pages):
        try:
            if p.url and "didi" in p.url:
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
