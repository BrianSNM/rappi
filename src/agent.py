import os
import json
import hashlib
import re
from pathlib import Path
from typing import Optional
import google.generativeai as genai
from pydantic import BaseModel, Field

CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
_model = genai.GenerativeModel("gemini-2.5-flash")


class ProductMatch(BaseModel):
    match_score: float = Field(ge=0, le=1)
    is_same_product: bool
    promotion_type: Optional[str] = None
    canonical_label: str


class MetricExtraction(BaseModel):
    subtotal: Optional[float] = None
    delivery_fee: Optional[float] = None
    service_fee: Optional[float] = None
    eta_min: Optional[int] = None
    discount_detected: bool = False
    promotion_type: Optional[str] = None


def _cache_key(prefix: str, payload: str) -> Path:
    h = hashlib.md5(payload.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{prefix}_{h}.json"


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text


def _cached_call(prefix: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    cache_file = _cache_key(prefix, prompt)
    if cache_file.exists():
        return schema.model_validate_json(cache_file.read_text())

    resp = _model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    cleaned = _strip_fences(resp.text)
    parsed = schema.model_validate_json(cleaned)
    cache_file.write_text(parsed.model_dump_json())
    return parsed


def match_product(scraped_name: str, target_label: str, target_category: str) -> ProductMatch:
    prompt = f"""Eres un experto en delivery apps en Mexico. Determina si el producto scrapeado coincide con el objetivo.

Producto scrapeado: "{scraped_name}"
Producto objetivo: "{target_label}" (categoria: {target_category})

Responde SOLO con un JSON valido con este esquema exacto:
{{
  "match_score": <float 0-1>,
  "is_same_product": <true|false>,
  "promotion_type": <string o null>,
  "canonical_label": <string normalizado>
}}"""
    return _cached_call("match", prompt, ProductMatch)


def extract_checkout_metrics(raw_text: str, platform: str) -> MetricExtraction:
    prompt = f"""Extrae las metricas del checkout de {platform}. Texto del DOM:

\"\"\"{raw_text[:3000]}\"\"\"

Responde SOLO con un JSON valido con este esquema exacto (todos los valores numericos en MXN, sin simbolos):
{{
  "subtotal": <float o null>,
  "delivery_fee": <float o null>,
  "service_fee": <float o null>,
  "eta_min": <int minutos promedio o null>,
  "discount_detected": <true|false>,
  "promotion_type": <string descriptivo o null>
}}"""
    return _cached_call(f"metrics_{platform}", prompt, MetricExtraction)


def discover_products_in_city(city: str, platforms_inventory: dict[str, list[str]]) -> dict:
    prompt = f"""Para la ciudad de {city}, dado el inventario de cada plataforma, identifica para cada uno de estos
4 productos canonicos cual es el item exacto disponible en las 3 plataformas (o el mas parecido):

Productos canonicos:
- big_mac (Big Mac de McDonald's)
- kfc_bucket_8 (KFC Bucket 8 piezas)
- coca_600ml (Coca-Cola 600ml, fallback: misma marca presentacion cercana)
- agua_1l (Agua Ciel 1L, fallback: marca Ciel o similar 1-1.5L)

Inventario por plataforma:
{json.dumps(platforms_inventory, ensure_ascii=False, indent=2)[:4000]}

Responde SOLO con un JSON valido con este esquema:
{{
  "big_mac":      {{"rappi": <string>, "uber": <string>, "didi": <string>}},
  "kfc_bucket_8": {{"rappi": <string>, "uber": <string>, "didi": <string>}},
  "coca_600ml":   {{"rappi": <string>, "uber": <string>, "didi": <string>}},
  "agua_1l":      {{"rappi": <string>, "uber": <string>, "didi": <string>}}
}}"""
    resp = _model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(_strip_fences(resp.text))
