"""
Test Rappi E2E COMPLETO Y CERRADO: dir -> agregar -> checkout -> capturar -> vaciar carrito.
"""
import asyncio
import os
import re
from playwright.async_api import async_playwright, Page

ZONE = {"id": "cdmx_polanco", "address": "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"}
MERCHANT_ALT = "McDonald's"
PRODUCT = "Big Mac"
SHOTS = "data/screenshots"
os.makedirs(SHOTS, exist_ok=True)


async def step(page: Page, n, name, fn):
    print(f"\n>>> {n}. {name}")
    input("    [ENTER]")
    try:
        await fn()
        print(f"    OK")
        return True
    except Exception as e:
        shot = f"{SHOTS}/test_FAIL_{n}.png"
        try:
            await page.screenshot(path=shot, full_page=False)
            print(f"    FAIL: {type(e).__name__}: {str(e)[:200]}")
            print(f"    Screenshot: {shot}")
        except Exception:
            pass
        return False


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

    eta_range = re.search(r"Entrega estimada:?\s*(\d+)\s*[-a]\s*(\d+)\s*min", text)
    if eta_range:
        metrics["eta_min"] = (int(eta_range.group(1)) + int(eta_range.group(2))) // 2
    else:
        eta_single = re.search(r"(\d+)\s*min", text)
        metrics["eta_min"] = int(eta_single.group(1)) if eta_single else None

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
        except Exception:
            pass

    page = await ctx.new_page()

    if not await step(page, 1, "Cargar rappi.com.mx",
        lambda: page.goto("https://www.rappi.com.mx/", wait_until="networkidle", timeout=60000)): return
    await asyncio.sleep(3)

    try:
        b = page.locator('button:has-text("Ok, entendido")').first
        if await b.count() > 0 and await b.is_visible():
            await b.click(timeout=2000)
    except Exception:
        pass

    if not await step(page, 2, "Click address-container",
        lambda: page.click('[data-qa="address-container"]', timeout=15000)): return
    await asyncio.sleep(2)

    if not await step(page, 3, "Llenar address-input",
        lambda: page.fill('[data-qa="address-input"]', ZONE["address"], timeout=15000)): return
    await asyncio.sleep(3)

    if not await step(page, 4, "Click suggestion-item",
        lambda: page.locator('[data-qa="suggestion-item"]').first.click(timeout=10000)): return
    await asyncio.sleep(4)

    if not await step(page, 5, "Click 'Confirmar direccion'",
        lambda: page.locator('button:has-text("Confirmar")').first.click(timeout=10000)): return
    await asyncio.sleep(3)

    if not await step(page, 6, "Click 'Guardar direccion'",
        lambda: page.locator('button:has-text("Guardar")').first.click(timeout=10000)): return
    await asyncio.sleep(4)

    if not await step(page, 7, f"Click McDonald's via '10 mas elegidos'",
        lambda: page.locator(
            f'a[href*="/restaurantes/delivery/"]:has(img[alt="{MERCHANT_ALT}"])'
        ).first.click(timeout=15000)): return
    await asyncio.sleep(6)

    if not await step(page, 8, f"Buscar '{PRODUCT}'",
        lambda: _search(page, PRODUCT)): return
    await asyncio.sleep(4)

    print(f"\n>>> 9. Buscando product-item exacto")
    target_item = None
    for i in range(await page.locator('[data-qa^="product-item-"]').count()):
        try:
            item = page.locator('[data-qa^="product-item-"]').nth(i)
            first_line = (await item.inner_text()).split("\n")[0].strip()
            if first_line == PRODUCT and await item.is_visible():
                target_item = item; break
        except Exception:
            pass
    if target_item is None:
        print("    [!] No encontre producto"); return
    print("    OK")

    if not await step(page, 10, "Click product-item",
        lambda: target_item.click(timeout=10000)): return
    await asyncio.sleep(3)

    if not await step(page, 11, "Click 'Agregar' modal producto",
        lambda: page.locator('button:has-text("Agregar")').first.click(timeout=10000)): return
    await asyncio.sleep(3)

    if not await step(page, 12, "Click basket-icon",
        lambda: page.locator('[data-qa="basket-icon"]').click(timeout=10000)): return
    await asyncio.sleep(3)

    if not await step(page, 13, "Click 'Ir a pagar'",
        lambda: page.locator('[data-qa="go-to-pay-button"]').click(timeout=10000)): return
    await asyncio.sleep(5)

    print("\n>>> 14. Cerrar modal 'Un ultimo antojo' si aparece")
    try:
        antojo = page.locator('button:has-text("En otro momento")').first
        if await antojo.count() > 0 and await antojo.is_visible():
            await antojo.click(timeout=5000)
            print("    OK 'En otro momento'")
            await asyncio.sleep(3)
        else:
            print("    Sin modal antojo")
    except Exception:
        print("    Sin modal antojo")

    print("\n>>> 15. Capturar metricas")
    await asyncio.sleep(2)
    await page.screenshot(path=f"{SHOTS}/test_15_checkout.png", full_page=True)
    text = await page.locator("body").inner_text()
    metrics = extract_metrics(text)
    print(f"    Metricas: {metrics}")

    print("\n>>> 16. Vaciar carrito (home + abrir + 'Vaciar todas las canastas' es <p>)")
    input("    [ENTER]")
    try:
        await page.goto("https://www.rappi.com.mx/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        print("    Home cargada")

        # Verificar si el panel ya esta abierto (a veces se abre solo)
        empty_p = page.locator('p:has-text("Vaciar todas las canastas")').first
        if await empty_p.count() == 0 or not await empty_p.is_visible():
            await page.locator('[data-qa="basket-icon"]').click(timeout=10000)
            await asyncio.sleep(2)
            print("    Carrito abierto via basket-icon")
        else:
            print("    Carrito ya estaba abierto")

        # Click en el <p> "Vaciar todas las canastas"
        empty_p = page.locator('p:has-text("Vaciar todas las canastas")').first
        if await empty_p.count() > 0 and await empty_p.is_visible():
            await empty_p.click(timeout=5000)
            print("    'Vaciar todas las canastas' clickeado")
            await asyncio.sleep(2)

            # Confirmar "Si, seguro" / "Sí, seguro"
            confirm = page.locator('button:has-text("seguro")').first
            if await confirm.count() > 0 and await confirm.is_visible():
                await confirm.click(timeout=5000)
                await asyncio.sleep(2)
                print("    OK 'Si, seguro' clickeado")
            else:
                print("    [!] No encontre boton de confirmacion")
        else:
            print("    [!] No encontre 'Vaciar todas las canastas'")

        await page.screenshot(path=f"{SHOTS}/test_16_after_clear.png", full_page=False)
    except Exception as e:
        print(f"    FAIL: {e}")

    print(f"\n=== Test E2E COMPLETO ===")
    print(f"=== Metricas: {metrics} ===")


async def _search(page, term):
    await page.fill('[data-qa="input"]', term, timeout=10000)
    await page.keyboard.press("Enter")


if __name__ == "__main__":
    asyncio.run(main())
