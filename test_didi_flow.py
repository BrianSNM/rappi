"""
Test E2E DiDi Food.
"""
import asyncio
import os
import re
from playwright.async_api import async_playwright, Page

ZONE = {"id": "cdmx_polanco", "address": "Av. Presidente Masaryk 201, Polanco, Miguel Hidalgo, 11560 CDMX"}
PRODUCT = "Big Mac"
SHOTS = "data/screenshots/didi_test"
HOME_URL = "https://www.didi-food.com/es-MX/food/"
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
        "subtotal":     r"Subtotal de los productos[\s\n]*MX\$?\s*([\d.,]+)",
        "delivery_fee": r"Tarifa de entrega[\s\n]*MX\$?\s*([\d.,]+)",
        "service_fee":  r"Tarifa de servicio[\s\n]*MX\$?\s*([\d.,]+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        metrics[key] = parse_money(m.group(1)) if m else None

    eta_min = re.search(r"(\d+)\s*[-a]\s*(\d+)\s*Min", text)
    if eta_min:
        metrics["eta_min"] = (int(eta_min.group(1)) + int(eta_min.group(2))) // 2
    else:
        metrics["eta_min"] = None
    return metrics


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
    ctx = browser.contexts[0]

    print(f"Limpiando pestanas viejas (hay {len(ctx.pages)})")
    for p in list(ctx.pages):
        try:
            if p.url and "didi" in p.url:
                await p.close()
        except Exception:
            pass

    page = await ctx.new_page()

    if not await step(page, 1, "Cargar didi-food.com",
        lambda: page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)): return
    await asyncio.sleep(4)

    # 2. Click direccion (.poi-display-name)
    print("\n>>> 2. Inspeccion: identificar boton de direccion")
    candidates = [
        '.poi-display-name',
        '.icon-outlined_address',
        '.address',
        '.d-cur_address',
    ]
    for sel in candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")

    if not await step(page, 3, "Click en direccion (poi-display-name)",
        lambda: page.locator('.poi-display-name').first.click(timeout=10000)): return
    await asyncio.sleep(3)

    # 4. Inspeccionar input de direccion
    print("\n>>> 4. Inspeccion: input de direccion")
    inp_candidates = [
        '.el-floating__body input.el-input__inner',
        '.el-floating__body input',
        'input[placeholder*="Ingresa una direcci" i]',
        '.current-address input',
    ]
    for sel in inp_candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")
        if v > 0:
            for el in await page.locator(sel).all():
                if await el.is_visible():
                    placeholder = await el.get_attribute("placeholder")
                    print(f"      visible placeholder='{placeholder}'")
                    break

    if not await step(page, 5, "Llenar input de direccion",
        lambda: _fill_first_visible(page, inp_candidates, ZONE["address"])): return
    await asyncio.sleep(3)

    # 6. Click primera sugerencia
    print("\n>>> 6. Inspeccion: sugerencias")
    sug_candidates = [
        '.delivery-address__content',
        '.el-floating__body .delivery-address__content',
    ]
    for sel in sug_candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")
        if v > 0:
            for i, el in enumerate((await page.locator(sel).all())[:3]):
                if await el.is_visible():
                    text = (await el.inner_text())[:60].replace("\n", " ")
                    print(f"      [{i}] '{text}'")

    if not await step(page, 7, "Click primera sugerencia",
        lambda: _click_first_visible(page, sug_candidates, must_contain="Polanco")): return
    await asyncio.sleep(6)

    # 7b. Modal "Direccion de entrega" -> click "Oficina" (es <div>) + "Confirmar" (es <button>)
    print("\n>>> 7b. Modal 'Direccion de entrega': click Oficina + Confirmar")
    try:
        # Oficina es un DIV con clase infos-type_text
        oficina = page.locator('.infos-type_text:has-text("Oficina")').first
        if await oficina.count() == 0:
            # fallback: cualquier elemento hoja con texto Oficina
            oficina = page.locator('div:text-is("Oficina")').first
        if await oficina.count() > 0 and await oficina.is_visible():
            await oficina.click(timeout=5000)
            print("    OK 'Oficina' clickeado")
            # Esperar mas tiempo para que el modal se actualice tras seleccion
            await asyncio.sleep(3)
            try:
                # Confirmar es un BUTTON (hay un DIV con mismo texto, filtramos por tag)
                confirmar = page.locator('button.el-button:has(span:text-is("Confirmar"))').first
                # Scroll por si el boton esta fuera de viewport
                try:
                    await confirmar.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                await asyncio.sleep(0.5)
                await confirmar.click(timeout=5000, force=True)
                print("    OK 'Confirmar' clickeado")
                await asyncio.sleep(5)
                # Verificar que el modal se cerro
                modal_still_open = await page.locator('button.el-button:has(span:text-is("Confirmar"))').count()
                if modal_still_open > 0 and await page.locator('button.el-button:has(span:text-is("Confirmar"))').first.is_visible():
                    print("    [!] Modal sigue abierto tras Confirmar, intentando 2do click...")
                    await page.locator('button.el-button:has(span:text-is("Confirmar"))').first.click(timeout=5000, force=True)
                    await asyncio.sleep(4)
            except Exception as e_inner:
                print(f"    [!] No pude clickear 'Confirmar': {e_inner}")
        else:
            print("    Sin modal de tipo de ubicacion (no aparece o ya cerrado)")
    except Exception as e:
        print(f"    Error en 7b: {e}")

    await page.screenshot(path=f"{SHOTS}/test_07_after_address.png", full_page=False)

    # 8. Buscar McDonald's
    print("\n>>> 8. Buscar 'Mcdonalds'")
    search_candidates = [
        'input[placeholder*="restaurantes" i]',
        'input[placeholder*="comida" i]',
        'input[placeholder*="busca" i]',
        'input[type="search"]',
    ]
    for sel in search_candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")

    if not await step(page, 9, "Llenar buscador con 'Mcdonalds'",
        lambda: _fill_first_visible(page, search_candidates, "Mcdonalds", press_enter=True)): return
    await asyncio.sleep(6)

    await page.screenshot(path=f"{SHOTS}/test_09_search.png", full_page=False)

    # 10. Click primera shop-card de McDonald's
    print("\n>>> 10. Inspeccion: buscar McDonald's clickable")
    # Estrategia: buscar el ancestro <a> de la imagen alt=McDonald's
    target = None
    mcd_imgs = await page.locator('img[alt*="McDonald" i]').all()
    print(f"    Total imgs McDonald: {len(mcd_imgs)}")
    for i, img in enumerate(mcd_imgs[:8]):
        try:
            visible = await img.is_visible()
            if not visible: continue
            # Subir al ancestor <a> o div clickable
            parent_info = await img.evaluate("""img => {
                let cur = img;
                for (let i = 0; i < 12 && cur; i++) {
                    if (cur.tagName === 'A') return {found: 'a', i: i, href: cur.href};
                    cur = cur.parentElement;
                }
                return null;
            }""")
            print(f"    [{i}] visible parent={parent_info}")
            if parent_info and parent_info.get('found') == 'a' and target is None:
                # locator del <a> ancestor
                target = img.locator('xpath=ancestor::a[1]')
                print(f"      >> SELECCIONADO (ancestor <a>)")
                break
        except Exception as e:
            print(f"    [{i}] error: {e}")

    if target is None:
        print("    Fallback: usar el .shop-card padre de la primera img McDonald")
        first_img = page.locator('img[alt*="McDonald" i]').first
        target = first_img.locator('xpath=ancestor::*[contains(@class, "shop-card") or contains(@class, "shop-item")][1]')
        if await target.count() == 0:
            print("    [!] Ningun ancestor clickable, usando img directamente")
            target = first_img

    if not await step(page, 11, "Click primera tarjeta McDonald's",
        lambda: target.click(timeout=10000)): return
    await asyncio.sleep(6)

    print(f"\n>>> 12. URL menu: {page.url}")
    await page.screenshot(path=f"{SHOTS}/test_12_menu.png", full_page=False)

    # 13. Buscar tarjeta exacta Big Mac y click "Agregar"
    print(f"\n>>> 13. Buscando '{PRODUCT}' en tarjetas item-card")
    items = await page.locator('.item-card').all()
    print(f"    Total item-card: {len(items)}")
    target_item = None
    for i, item in enumerate(items):
        try:
            text = (await item.inner_text())[:100]
            first_line = text.split("\n")[0].strip()
            if first_line == PRODUCT and await item.is_visible():
                target_item = item
                print(f"    [{i}] MATCH titulo exacto '{first_line}'")
                break
        except Exception:
            pass

    if target_item is None:
        # Fallback: buscar elemento con texto exacto Big Mac y subir al .item-card
        print("    Fallback: buscar via text=/^Big Mac$/")
        bm = page.locator(f'text=/^{PRODUCT}$/i')
        cnt = await bm.count()
        print(f"    Encontrados '{PRODUCT}' exactos: {cnt}")
        if cnt > 0:
            for i in range(cnt):
                el = bm.nth(i)
                if await el.is_visible():
                    # Subir al .item-card padre
                    parent = el.locator('xpath=ancestor::*[contains(@class, "item-card")][1]')
                    if await parent.count() > 0:
                        target_item = parent.first
                        print("    OK encontrado via fallback")
                        break

    if target_item is None:
        print("    [!] No encontre Big Mac")
        return

    if not await step(page, 14, "Click 'Agregar' dentro de la tarjeta Big Mac",
        lambda: target_item.locator('button:has-text("Agregar")').first.click(timeout=10000)): return
    await asyncio.sleep(3)

    await page.screenshot(path=f"{SHOTS}/test_14_modal.png", full_page=False)

    # 15. Modal del producto -> click "Agregar MX$125" (el grande naranja)
    print("\n>>> 15. Inspeccion: boton 'Agregar' del modal del producto")
    add_candidates = [
        '.add-btn',
        'button:has-text("Agregar")',
    ]
    for sel in add_candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")

    if not await step(page, 16, "Click 'Agregar' en modal (boton grande naranja)",
        lambda: _click_modal_agregar(page)): return
    await asyncio.sleep(4)

    # 17. Pop-up abajo derecha "Pagar" (queda permanente)
    print("\n>>> 17. Click 'Pagar' del pop-up mini-cart abajo derecha")
    pagar_candidates = [
        '.mini-cart button:has-text("Pagar")',
        'button:has-text("Pagar")',
    ]
    for sel in pagar_candidates:
        c = await page.locator(sel).count()
        v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
        print(f"    {sel} -> count={c} visibles={v}")

    if not await step(page, 18, "Click 'Pagar'",
        lambda: page.locator('button:has-text("Pagar")').first.click(timeout=10000)): return
    await asyncio.sleep(6)

    # 19. Capturar metricas
    print(f"\n>>> 19. URL checkout: {page.url}")
    await page.screenshot(path=f"{SHOTS}/test_19_checkout.png", full_page=True)
    text = await page.locator("body").inner_text()
    metrics = extract_metrics(text)
    print(f"\n    Metricas: {metrics}")

    # 20. Volver a home, click "Ver carrito", basura, confirmar
    print("\n>>> 20. Volver a home y vaciar carrito")
    input("    [ENTER]")
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        # Click "Ver carrito" (boton naranja abajo derecha)
        ver_carrito_candidates = [
            'button:has-text("Ver carrito")',
            'a:has-text("Ver carrito")',
            ':text("Ver carrito")',
        ]
        for sel in ver_carrito_candidates:
            cnt = await page.locator(sel).count()
            print(f"    {sel} -> count={cnt}")

        clicked = False
        for sel in ver_carrito_candidates:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click(timeout=5000)
                    print(f"    OK 'Ver carrito' clickeado via {sel}")
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            print("    [!] No se pudo abrir 'Ver carrito'")
            return
        await asyncio.sleep(3)

        # Click papelera (cart-item-delete o icon-outlined_delete)
        print("\n    Buscando papelera...")
        trash_candidates = [
            '.cart-item-delete',
            '.icon-outlined_delete',
            'i[class*="delete" i]',
        ]
        for sel in trash_candidates:
            c = await page.locator(sel).count()
            v = sum([1 for el in (await page.locator(sel).all()) if await el.is_visible()])
            print(f"    {sel} -> count={c} visibles={v}")

        for sel in trash_candidates:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click(timeout=5000)
                    print(f"    OK papelera clickeada via {sel}")
                    break
            except Exception:
                pass
        await asyncio.sleep(2)

        # Click "Confirmar" del modal de vaciado (clase el-new-alert-highlight)
        try:
            await asyncio.sleep(1)
            confirm = page.locator('button.el-new-alert-highlight').first
            if await confirm.count() == 0 or not await confirm.is_visible():
                # fallback: cualquier button con texto Confirmar
                confirm = page.locator('button:has-text("Confirmar")').last
            await confirm.click(timeout=5000, force=True)
            print("    OK 'Confirmar' clickeado")
            await asyncio.sleep(3)
            # Verificar que el modal se cerro, si no, segundo click
            still = page.locator('button.el-new-alert-highlight').first
            if await still.count() > 0 and await still.is_visible():
                print("    [!] Modal de vaciado sigue abierto, segundo click")
                await still.click(timeout=5000, force=True)
                await asyncio.sleep(3)
        except Exception as e:
            print(f"    Error confirmacion: {e}")

        await page.screenshot(path=f"{SHOTS}/test_20_after_clear.png", full_page=False)

    except Exception as e:
        print(f"    FAIL: {e}")

    print(f"\n=== Test E2E completo ===")
    print(f"=== Metricas: {metrics} ===")


async def _fill_first_visible(page, selectors, text, press_enter=False):
    for sel in selectors:
        for el in (await page.locator(sel).all()):
            try:
                if await el.is_visible():
                    await el.fill(text, timeout=5000)
                    if press_enter:
                        await page.keyboard.press("Enter")
                    return
            except Exception:
                continue
    raise Exception(f"Ningun selector visible: {selectors}")


async def _click_first_visible(page, selectors, must_contain=None):
    for sel in selectors:
        for el in (await page.locator(sel).all()):
            try:
                if not await el.is_visible():
                    continue
                if must_contain:
                    txt = (await el.inner_text())
                    if must_contain.lower() not in txt.lower():
                        continue
                await el.click(timeout=5000)
                return
            except Exception:
                continue
    raise Exception(f"Ningun selector clickable: {selectors}")


async def _click_modal_agregar(page):
    # En el modal hay un boton .add-btn o un boton "Agregar" GRANDE (no el de la tarjeta)
    # Probamos add-btn primero
    add_btn = page.locator('.add-btn').first
    if await add_btn.count() > 0 and await add_btn.is_visible():
        await add_btn.click(timeout=5000)
        return
    # Fallback: el ultimo boton "Agregar" visible (el del modal suele ser el ultimo)
    btns = await page.locator('button:has-text("Agregar")').all()
    visible_btns = [b for b in btns if await b.is_visible()]
    if visible_btns:
        await visible_btns[-1].click(timeout=5000)
        return
    raise Exception("No encontre boton Agregar del modal")


if __name__ == "__main__":
    asyncio.run(main())
