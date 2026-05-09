"""
Setup inicial del perfil dedicado del proyecto.

Lanza Chrome con el perfil ./browser_profile/ y abre las 3 plataformas en pestanas.
Tu haces login MANUALMENTE en cada una. Despues cierras Chrome y las sesiones
quedan persistidas en ese perfil para uso del scraper.

Esto se hace UNA SOLA VEZ. Despues no necesitas volver a loguearte.
"""
import os
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROFILE_DIR = Path("browser_profile").resolve()
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

binary = os.getenv("CHROME_BINARY", "/usr/bin/google-chrome")

print(f"Lanzando Chrome con perfil dedicado en: {PROFILE_DIR}")
print("Pestanas abiertas:")
print("  1. Rappi MX")
print("  2. Uber Eats MX")
print("  3. DiDi Food MX")
print("")
print("INSTRUCCIONES:")
print("  - Haz login en cada una de las 3 plataformas con tu cuenta")
print("  - Cuando termines, cierra Chrome")
print("  - Las sesiones quedaran guardadas para el scraper")
print("")

proc = subprocess.Popen([
    binary,
    f"--user-data-dir={PROFILE_DIR}",
    "--no-first-run",
    "--no-default-browser-check",
    "https://www.rappi.com.mx/",
    "https://www.ubereats.com/mx",
    "https://www.didi-food.com/es-MX/food/feed",
])

print(f"Chrome lanzado (pid {proc.pid}). Esperando a que cierres el navegador...")
proc.wait()
print("Chrome cerrado. Sesiones guardadas en browser_profile/")
