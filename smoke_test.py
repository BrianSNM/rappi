"""Smoke test: valida Chrome CDP + Gemini + dependencias."""
import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def check_env():
    print("[1/4] Variables de entorno...")
    key = os.getenv("GEMINI_API_KEY")
    if not key or key == "tu_api_key_aqui":
        print("  FAIL: GEMINI_API_KEY no configurada en .env")
        return False
    print(f"  OK: GEMINI_API_KEY presente ({key[:8]}...)")
    return True


def check_gemini():
    print("[2/4] Gemini SDK...")
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        m = genai.GenerativeModel("gemini-2.5-flash")
        r = m.generate_content("Responde solo: OK")
        print(f"  OK: respuesta = {r.text.strip()[:50]}")
        return True
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return False


def check_chrome():
    print("[3/4] Chrome con debugging port...")
    print("  Asegurate de haber CERRADO Chrome antes de continuar.")
    input("  Presiona ENTER cuando Chrome este cerrado...")
    from src.engine import launch_chrome_with_debug
    proc = launch_chrome_with_debug()
    print(f"  OK: Chrome lanzado (pid {proc.pid})")
    return proc


async def check_playwright(proc):
    print("[4/4] Playwright + CDP...")
    try:
        from src.engine import get_browser
        pw, browser = await get_browser()
        ctxs = browser.contexts
        print(f"  OK: conectado. Contexts: {len(ctxs)}, pages totales: {sum(len(c.pages) for c in ctxs)}")

        ctx = ctxs[0] if ctxs else await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://www.rappi.com.mx/", timeout=30000)
        title = await page.title()
        print(f"  OK: rappi.com.mx carga -> '{title[:60]}'")
        await page.close()
        await pw.stop()
        return True
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return False


def main():
    if not check_env(): sys.exit(1)
    if not check_gemini(): sys.exit(1)
    proc = check_chrome()
    try:
        ok = asyncio.run(check_playwright(proc))
        if ok:
            print("\nTodo OK. Listos para Fase 2 (calibrar selectores).")
        else:
            sys.exit(1)
    finally:
        print("\nDejo Chrome abierto para que sigas con la calibracion manual.")


if __name__ == "__main__":
    main()
