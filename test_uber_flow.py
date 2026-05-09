"""
Test E2E Uber Eats: dir -> McDonald's -> Big Mac -> Agregar -> checkout -> capturar -> vaciar.
"""
import asyncio
import os
import re
from playwright.async_api import async_playwright, Page

ZONE = {"id": "cdmx_polanco", "address": "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"}
MERCHANT = "McDonald"
PRODUCT = "Big Mac"
SHOTS = "data/screenshots/uber_test"
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
        "subtotal":     r"Subtotal[\s\n]*\$\s*([\d.,]+)",
        "delivery_fee": r"Costo de env[ií]o[\s\n]*\$\s*([\d.,]+)",
        "service_fee":  r"Cuota de servicio[\s\n]*\$\s*([\d.,]+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        metrics[key] = parse_money(m.group(1)) if m else None

    eta_min = re.search(r"(\d+)\s*[-a]\s*(\d+)\s*min", text)
    if eta_min:
        metrics["eta_min"] = (int(eta_min.group(1)) + int(eta_min.group(2))) // 2
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
            if p.url and "ubereats" in p.url:
                await p.close()
        except Exception:
            pass

    page = await ctx.new_page()

    if not await step(page, 1, "Cargar ubereats.com/mx",
        lambda: page.goto("https://www.ubereats.com/mx", wait_until="domcontentloaded", timeout=60000)): return
    await asyncio.sleep(3)

    # 2. Click en boton de direccion (texto "Polanco · Ahora" o lo que sea actual)
    # El selector estable parece ser button con icono de location pin
    print("\n>>> 2. Inspeccion: identificar boton de direccion")
    candidates = [
        'button:has-text("Ahora")',
        'button[aria-label*="direccion" i]',
        'button[aria-label*="address" i]',
        '[data-test*="address" i]',
        '[data-testid*="address" i]',
    ]
    for sel in candidates:
        c = await page.locator(sel).count()
        print(f"    {sel} -> count={c}")
    input("    [ENTER para click en el primero que tenga count>0]")

    # Tomar el primer candidato disponible
    addr_btn = None
    for sel in candidates:
        if await page.locator(sel).count() > 0:
            addr_btn = page.locator(sel).first
            break

    if addr_btn is None:
        print("    [!] No se encontro boton de direccion. Abortando.")
        return
    try:
        await addr_btn.click(timeout=10000)
        print("    OK")
    except Exception as e:
        print(f"    FAIL: {e}")
        return
    await asyncio.sleep(3)

    print("\n>>> 3. Modal 'Direcciones' abierto - inspeccionando input")
    candidates = [
        'input[placeholder*="direccion" i]',
        'input[placeholder*="busca" i]',
        'input[type="search"]',
        '[data-testid*="address-input" i]',
    ]
    addr_input = None
    for sel in candidates:
        c = await page.locator(sel).count()
        print(f"    {sel} -> count={c}")
        if c > 0 and addr_input is None:
            addr_input = page.locator(sel).first

    if not await step(page, 4, "Llenar input de direccion",
        lambda: addr_input.fill(ZONE["address"], timeout=10000)): return
    await asyncio.sleep(3)

    print("\n>>> 5. Inspeccion: sugerencias de direccion")
    # Las sugerencias suelen ser <li> o <button> dentro del modal
    sug_candidates = [
        'li[role="option"]',
        '[data-baseweb*="menu"] [role="option"]',
        'ul li',
    ]
    for sel in sug_candidates:
        c = await page.locator(sel).count()
        if c > 0:
            print(f"    {sel} -> count={c}")
            for i in range(min(c, 3)):
                try:
                    text = (await page.locator(sel).nth(i).inner_text())[:60].replace("\n", " ")
                    print(f"      [{i}] '{text}'")
                except Exception:
                    pass

    if not await step(page, 6, "Click primera sugerencia",
        lambda: page.locator('li[role="option"]').first.click(timeout=10000)): return
    await asyncio.sleep(4)

    # 7. Modal "Elige tu edificio" -> Omitir
    print("\n>>> 7. Detectar modal 'Elige tu edificio' y click 'Omitir'")
    try:
        omitir = page.locator('button:has-text("Omitir")').first
        if await omitir.count() > 0 and await omitir.is_visible():
            await omitir.click(timeout=5000)
            print("    OK 'Omitir' clickeado")
            await asyncio.sleep(3)
        else:
            print("    Sin modal de edificio")
    except Exception as e:
        print(f"    Error 'Omitir': {e}")

    # 7b. Modal "Informacion de la direccion" -> Guardar
    print("\n>>> 7b. Detectar modal 'Informacion de la direccion' y click 'Guardar'")
    try:
        guardar = page.locator('button:has-text("Guardar")').first
        if await guardar.count() > 0 and await guardar.is_visible():
            await guardar.click(timeout=5000)
            print("    OK 'Guardar' clickeado")
            await asyncio.sleep(4)
        else:
            print("    Sin modal de informacion")
    except Exception as e:
        print(f"    Error 'Guardar': {e}")

    # Captura de pantalla intermedia
    await page.screenshot(path=f"{SHOTS}/test_07_after_address.png", full_page=False)

    # 8. Buscar McDonald's en header
    print(f"\n>>> 8. Buscar '{MERCHANT}' en header search")
    search_candidates = [
        'input[placeholder*="Buscar en Uber Eats" i]',
        'input[placeholder*="Buscar" i]',
        'input[type="search"]',
    ]
    for sel in search_candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")
    input("    [ENTER para llenar buscador]")
    try:
        # tomar el visible
        for sel in search_candidates:
            for el in (await page.locator(sel).all()):
                if await el.is_visible():
                    await el.fill("mcdonalds", timeout=10000)
                    await page.keyboard.press("Enter")
                    print("    OK busqueda enviada")
                    break
            else:
                continue
            break
        await asyncio.sleep(8)
        try:
            await page.wait_for_selector('[data-testid="store-card"]', timeout=15000)
        except Exception:
            print("    [!] Timeout esperando store-cards de resultado")
    except Exception as e:
        print(f"    FAIL: {e}")
        return

    await page.screenshot(path=f"{SHOTS}/test_08_search.png", full_page=False)

    # 9. Inspeccionar store-cards y descartar anuncio "Patrocinado"
    print("\n>>> 9. Inspeccionando store-cards (descartar 'Patrocinado')")
    cards = await page.locator('[data-testid="store-card"]').all()
    print(f"    Total store-card: {len(cards)}")
    target_card = None
    for i, c in enumerate(cards[:5]):
        try:
            text = (await c.inner_text())[:200].replace("\n", " | ")
            visible = await c.is_visible()
            is_ad = "Patrocinado" in text
            print(f"    [{i}] visible={visible} ad={is_ad} text='{text[:120]}'")
            if not is_ad and ("McDonald" in text or "Mcdonald" in text) and target_card is None:
                target_card = c
                print(f"      >> SELECCIONADO")
        except Exception:
            pass

    if target_card is None:
        print("    [!] No encontre store-card de McDonald's no patrocinado")
        return

    if not await step(page, 10, "Click en store-card de McDonald's",
        lambda: target_card.click(timeout=10000)): return
    await asyncio.sleep(6)

    print(f"\n>>> 11. URL del menu: {page.url}")
    await page.screenshot(path=f"{SHOTS}/test_11_menu.png", full_page=False)

    # 12. Buscador interno
    print("\n>>> 12. Buscador interno del restaurante")
    candidates = [
        f'input[placeholder*="Buscar en {MERCHANT}" i]',
        'input[placeholder*="Buscar en" i]',
        'input[type="search"]',
    ]
    for sel in candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")
    input("    [ENTER para buscar Big Mac]")
    try:
        for sel in candidates:
            for el in await page.locator(sel).all():
                if await el.is_visible():
                    await el.fill(PRODUCT, timeout=10000)
                    print("    OK busqueda interna")
                    break
            else:
                continue
            break
        await asyncio.sleep(4)
    except Exception as e:
        print(f"    FAIL: {e}")
        return

    await page.screenshot(path=f"{SHOTS}/test_12_search_bigmac.png", full_page=False)

    # 13. Encontrar tarjeta de Big Mac (titulo exacto, no "McTrio Big Mac")
    print(f"\n>>> 13. Buscando tarjeta exacta '{PRODUCT}'")
    # En Uber las tarjetas suelen ser <a> o <li> con un <h4>/<span> que es el titulo
    # Identificamos por texto exacto
    bm_locator = page.locator(f'text=/^{PRODUCT}$/')
    count = await bm_locator.count()
    print(f"    Total textos exactos '{PRODUCT}': {count}")
    target = None
    for i in range(count):
        try:
            el = bm_locator.nth(i)
            text = (await el.inner_text()).strip()
            visible = await el.is_visible()
            # Subir al ancestro clickable
            container_info = await el.evaluate("""el => {
                let cur = el;
                for (let i = 0; i < 10 && cur; i++) {
                    if (cur.tagName === 'A' || cur.tagName === 'BUTTON' ||
                        cur.getAttribute && (cur.getAttribute('data-testid') === 'rich-item' ||
                                             cur.getAttribute('role') === 'button')) {
                        return {tag: cur.tagName, testid: cur.getAttribute('data-testid'), depth: i,
                                role: cur.getAttribute('role')};
                    }
                    cur = cur.parentElement;
                }
                return null;
            }""")
            print(f"    [{i}] text='{text}' visible={visible} container={container_info}")
            if visible and target is None:
                target = el
        except Exception as e:
            print(f"    [{i}] error: {e}")

    if target is None:
        print("    [!] No encontre 'Big Mac' visible")
        return

    if not await step(page, 14, "Click en Big Mac",
        lambda: target.click(timeout=10000)): return
    await asyncio.sleep(3)

    # 15. Modal del producto -> Click "Agregar X al pedido"
    print("\n>>> 15. Modal del producto - inspeccionar boton Agregar")
    add_candidates = [
        'button:has-text("Agregar")',
        'button:has-text("al pedido")',
    ]
    for sel in add_candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in await page.locator(sel).all() if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")

    if not await step(page, 16, "Click 'Agregar al pedido'",
        lambda: page.locator('button:has-text("Agregar")').filter(
            has_text=re.compile("pedido|al pedido", re.I)
        ).first.click(timeout=10000)): return
    await asyncio.sleep(3)

    # 17. Pop-up "Se agrego al carrito" -> click "Continuar" INMEDIATO (dura 2s)
    print("\n>>> 17. Pop-up 'Se agrego' aparece - click 'Continuar' inmediato")
    # No hay ENTER aqui porque el pop-up se cierra solo en 2s
    await asyncio.sleep(0.8)
    try:
        cont = page.locator('button:has-text("Continuar")').first
        await cont.click(timeout=3000)
        print("    OK 'Continuar' del pop-up clickeado")
    except Exception as e:
        print(f"    [!] Pop-up se cerro o no encontrado: {e}")
        print("    Fallback: abrir carrito desde el icono del header")
        try:
            cart_btn = page.locator('[data-testid*="cart" i], a[href*="cart"]').first
            await cart_btn.click(timeout=5000)
            await asyncio.sleep(2)
            cont = page.locator('button:has-text("Continuar")').first
            await cont.click(timeout=5000)
            print("    OK 'Continuar' fallback")
        except Exception as e2:
            print(f"    FAIL fallback: {e2}")
            return
    await asyncio.sleep(5)

    # 18. Modal "Completa tu pedido" -> Omitir
    print("\n>>> 18. Modal 'Completa tu pedido' - click 'Omitir'")
    try:
        omitir = page.locator('button:has-text("Omitir")').first
        if await omitir.count() > 0 and await omitir.is_visible():
            await omitir.click(timeout=5000)
            print("    OK 'Omitir'")
            await asyncio.sleep(3)
        else:
            print("    Sin modal upsell")
    except Exception as e:
        print(f"    Error: {e}")

    # 20. Pantalla de checkout - capturar metricas
    print(f"\n>>> 20. URL del checkout: {page.url}")
    await page.screenshot(path=f"{SHOTS}/test_20_checkout.png", full_page=True)
    text = await page.locator("body").inner_text()
    metrics = extract_metrics(text)
    print(f"\n    Metricas: {metrics}")

    # 21. Vaciar carrito: navegar a home y eliminar con papelera
    print("\n>>> 21. Volver a home y vaciar carrito")
    input("    [ENTER]")
    try:
        await page.goto("https://www.ubereats.com/mx", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        # Click en carrito (icono arriba derecha)
        cart_candidates = [
            '[data-testid="topnav-cart-button"]',
            'button[aria-label*="carrito" i]',
            'button[aria-label*="cart" i]',
            'a[href*="cart"]',
        ]
        clicked = False
        for sel in cart_candidates:
            if await page.locator(sel).count() > 0:
                try:
                    await page.locator(sel).first.click(timeout=5000)
                    print(f"    Carrito abierto via {sel}")
                    clicked = True
                    break
                except Exception:
                    pass
        if not clicked:
            print("    [!] No pude abrir el carrito")
            return
        await asyncio.sleep(2)

        # Click en papelera/decrementar al lado del producto
        # Uber etiqueta el papelera como aria-label="Reduccion" o data-test="item-stepper-dec"
        print("    Buscando icono papelera (data-test=item-stepper-dec)...")
        try:
            trash = page.locator('button[data-test="item-stepper-dec"]').first
            if await trash.count() > 0:
                await trash.click(timeout=5000)
                print("    OK papelera clickeada")
                await asyncio.sleep(3)
            else:
                print("    [!] No encontre papelera")
        except Exception as e:
            print(f"    FAIL papelera: {e}")
        await page.screenshot(path=f"{SHOTS}/test_21_after_clear.png", full_page=False)
        # Volver a home limpio
        try:
            await page.goto("https://www.ubereats.com/mx", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            print("    OK volvi a home limpio")
        except Exception as e:
            print(f"    Error volviendo a home: {e}")

    except Exception as e:
        print(f"    FAIL: {e}")

    print(f"\n=== Test completo ===")
    print(f"=== Metricas: {metrics} ===")


if __name__ == "__main__":
    asyncio.run(main())
