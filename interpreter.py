"""
interpreter.py — Llamada a Gemini para interpretar los estadísticos.

Lee GEMINI_API_KEY de .env. Devuelve markdown listo para mostrar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Carga de .env si python-dotenv está instalado, si no lo intenta a mano
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


SYSTEM_PROMPT = """Eres un analista senior de Competitive Intelligence en Rappi (delivery LatAm).
Tu trabajo es interpretar resultados estadísticos para tres audiencias internas:

- **Pricing**: les importa subtotales, fees y elasticidad por zona/tier.
- **Operations**: les importan tiempos, cobertura, fee como % del valor total.
- **Strategy**: les importa posicionamiento competitivo y oportunidades de mercado.

CONTEXTO DEL PROBLEMA:
Rappi compite con Uber Eats, DiDi Food y otros en el mismo territorio. Necesitamos saber
si estamos posicionados como más caros, más baratos o similares; dónde tenemos ventaja;
y dónde estamos expuestos. La data viene de scraping geo-localizado (lat/lon, ciudad,
zona, tier socioeconómico) de 3 plataformas × 3 productos en direcciones representativas
de México (CDMX, Monterrey, Puebla).

REGLAS DE INTERPRETACIÓN:
1. NO repitas los números crudos del JSON; tradúcelos a implicaciones de negocio.
2. Si n es pequeño (n<10 en algún subgrupo), reconócelo explícitamente y usa lenguaje cauto
   ("la evidencia sugiere", "con la muestra disponible") en lugar de afirmaciones tajantes.
3. Distingue entre "diferencia significativa" (p<0.05 + IC que no cruza 0) y "tendencia
   sin significancia". No infles hallazgos no significativos.
4. Conecta cada hallazgo con UNA de las tres audiencias (Pricing/Operations/Strategy).
5. Si los datos muestran nulos sistemáticos en una plataforma, llámalo blocker de medición,
   no de negocio.
6. Sé directo y breve. No uses muletillas ni introducciones largas.

FORMATO DE SALIDA (markdown):
### 🎯 Hallazgo principal
Una frase con la conclusión más importante.

### 📊 Lectura por audiencia
- **Pricing:** ...
- **Operations:** ...
- **Strategy:** ...

### ⚠ Limitaciones
Caveats sobre tamaño de muestra, nulos, etc.

### 💡 Recomendación accionable
Una acción concreta y medible.
"""


def get_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def interpretar(resumen: dict, modelo: str = "gemini-flash-latest") -> str:
    """
    Envía los estadísticos a Gemini y devuelve la interpretación en markdown.
    Si falla, devuelve un mensaje de error legible.
    """
    api_key = get_api_key()
    if not api_key:
        return (
            "⚠ **No hay GEMINI_API_KEY en `.env`.**\n\n"
            "Edita el archivo `.env` y añade `GEMINI_API_KEY=tu_clave`."
        )

    try:
        import google.generativeai as genai
    except ImportError:
        return (
            "⚠ **Falta la librería.**\n\n"
            "Instala con: `pip install google-generativeai python-dotenv`"
        )

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=modelo,
            system_instruction=SYSTEM_PROMPT,
        )
        prompt = (
            "Estos son los estadísticos calculados sobre la muestra filtrada. "
            "Interprétalos siguiendo el formato indicado.\n\n"
            f"```json\n{json.dumps(resumen, ensure_ascii=False, indent=2, default=str)}\n```"
        )
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"⚠ **Error al llamar a Gemini:** `{type(e).__name__}: {e}`"
