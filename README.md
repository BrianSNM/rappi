# Rappi Intel — AI Engineer Tech Cases

Solución a los dos casos técnicos para la posición de AI Engineer en Rappi. Ambos casos viven en este mismo repositorio, conectados por una app Streamlit unificada de 4 pestañas.

---

## Quick start

```bash
# 1. Clonar
git clone <este-repo>
cd rappi-intel

# 2. Crear entorno (Python 3.12)
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar API key de Gemini (gratis en aistudio.google.com)
cp .env.example .env
# Editar .env y poner tu GEMINI_API_KEY o GOOGLE_API_KEY

# 5. Correr la app
streamlit run app.py
```

Los datos pre-procesados están en `data/`, así que la app arranca sin necesidad de correr el scraper ni el processor. Ver "Reproducir desde cero" más abajo si quieres regenerarlos.

---

## Las dos pruebas

### Prueba 1 — Sistema de Competitive Intelligence (scraping geo-localizado)

Recolección automatizada de precios y fees en Rappi, Uber Eats y DiDi Food, sobre 9 direcciones representativas en CDMX, Monterrey y Puebla, para 3 productos comparables (Big Mac, boneless bites, queso Caesar's).

**Pipeline:**
1. `run_scraper.py` ejecuta el scraping (orquesta `src/engine.py` y `src/agent.py`)
2. `clean_data.py` consolida los JSONs crudos en `data/clean.csv`
3. `geocode_addresses.py` resuelve cada dirección a `(lat, lon)` con Nominatim, cache en `data/geocache.json`
4. `merge_coords.py` enriquece el CSV con coordenadas

**Análisis estadístico** sobre `clean.csv`:
- Comparativa pareada con IC bootstrap (5,000 re-muestras), t-test pareado y Wilcoxon
- Manejo robusto de muestra pequeña (n=46): tres pruebas independientes que se cruzan para sostener cada hallazgo
- Interpretación con IA segmentada por audiencia (Pricing / Operations / Strategy)

### Prueba 2 — Sistema de Análisis Inteligente para Operaciones

**Bot conversacional (70% del peso)** sobre métricas operacionales en 9 países, implementado con **LangGraph** en lugar de un agente ReAct libre. Flujo determinista:

```
[generate_code] → [execute] → [verbalize]
                       ↓ error
                   [retry] → [execute]
```

Decisión técnica: 2-3 llamadas al LLM en el caso bueno (vs 5-10 con ReAct), latencia ~5-10 segundos, sin loops impredecibles.

**Sistema de insights automáticos (30%)** detecta hallazgos en 5 categorías:
1. Anomalías (cambios > 10% L1W → L0W)
2. Tendencias deteriorándose (pendiente negativa con monotonía 3+ semanas)
3. Benchmarking (z-score > 1.5 dentro de zonas comparables)
4. Correlaciones (|r| ≥ 0.5)
5. Oportunidades (alta Lead Penetration + bajo Perfect Orders)

Genera un reporte ejecutivo en markdown descargable con resumen, detalle por categoría y recomendaciones segmentadas.

---

## Las cuatro pestañas de la app

1. **🗺️ Mapa** — Visualización geoespacial con Pydeck, tooltip por dirección comparando plataformas, precios y fees.
2. **📊 Análisis Estadístico** — Cinco tablas con descriptivos, comparativa pareada, estructura de fees, consistencia (CV%) y cobertura competitiva. Botón de interpretación automatizada con Gemini.
3. **🤖 Operations Bot** — Chat con memoria conversacional sobre `master_data.parquet`. Cinco preguntas sugeridas, expander con código pandas generado por turno.
4. **📋 Reporte Ejecutivo** — Reporte automático con 6 sub-tabs: reporte completo descargable, detalle por categoría, **explorador interactivo de tendencias** (gráfico configurable por métrica y nivel: país/ciudad/zona) y **chatbot sobre oportunidades** (análisis explicativo + conversación de seguimiento).

---

## Estructura del repositorio

```
rappi-intel/
├── app.py                       # Streamlit con las 4 pestañas
├── analytics.py                 # Estadísticos prueba 1 (KPIs, pareada, fees, CV, cobertura)
├── interpreter.py               # Interpretación con Gemini para prueba 1
├── ops_bot.py                   # Bot LangGraph de prueba 2
├── ops_insights.py              # Detección de insights de prueba 2
│
├── src/                         # Motor del scraping (prueba 1)
│   ├── engine.py
│   ├── agent.py
│   └── analytics.py
│
├── config/                      # Configuración del scraper
│   ├── zones.json               # Direcciones objetivo
│   └── products.json            # Productos a buscar
│
├── scripts/
│   └── discover_products.py     # Auxiliar para descubrir productos
│
├── data/
│   ├── json/                    # JSONs crudos del scraping (prueba 1)
│   ├── clean.csv                # Output consolidado (prueba 1)
│   ├── clean.parquet            # Mismo contenido en parquet
│   ├── master_data.parquet      # Output del processor (prueba 2)
│   ├── geocache.json            # Cache de geocoding
│   ├── raw/                     # Snapshots adicionales
│   └── screenshots/             # Evidencia visual del scraping
│
├── browser_profile_*/           # Perfiles de Chrome para el scraping
│                                # (no se suben al repo, ver .gitignore)
│
├── clean_data.py                # Consolida JSONs → clean.csv
├── geocode_addresses.py         # Geocoding con Nominatim + fallback
├── merge_coords.py              # Enriquece clean.csv con lat/lon
├── geocoder.py                  # Módulo helper para geocoding
│
├── run_scraper.py               # Entrypoint del scraping
├── setup_browser_profile.py     # Inicializa los perfiles de Chrome
├── setup_project.sh             # Setup inicial del proyecto
├── fix_missing.sh               # Utilidad para reintentos
│
├── test_rappi_3products.py      # Validación interactiva por plataforma
├── test_uber_3products.py
├── test_didi_3products.py
├── test_rappi_flow.py           # Tests de flujo end-to-end
├── test_uber_flow.py
├── test_didi_flow.py
├── smoke_rappi.py               # Smoke tests
├── smoke_test.py
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md                    # Este archivo
```

---

## Stack técnico

| Componente | Versión / herramienta |
|---|---|
| Python | 3.12 |
| UI | Streamlit 1.39 + Pydeck 0.9 + Altair 5 |
| Datos | Pandas 2.2 + NumPy 2.x + PyArrow |
| Estadística | SciPy (t-test, Wilcoxon, regresiones) |
| LLM agents | LangChain 0.3 + LangGraph + langchain-google-genai |
| LLM | Google Generative AI (Gemini Flash) — gratis hasta 15 req/min |
| Scraping | Selenium + Chrome con perfil persistente |
| Geocoding | Nominatim (OpenStreetMap, gratis, sin API key) |

---

## Reproducir desde cero

### Prueba 1 — Generar `clean.csv` desde scraping

El scraping requiere Chrome con perfil persistente y puede ser bloqueado por las plataformas (especialmente Uber). Por eso los datos pre-scrapeados están incluidos en `data/`. Si aún así quieres regenerarlos:

```bash
# 1. Inicializar perfiles de Chrome (una vez)
python setup_browser_profile.py

# 2. Correr el scraping
python run_scraper.py

# 3. Limpiar y consolidar
python clean_data.py

# 4. Geocodificar direcciones
python geocode_addresses.py

# 5. Enriquecer CSV con coordenadas
python merge_coords.py
```

### Prueba 2 — Generar `master_data.parquet`

Requiere `datos.xlsx` con las hojas `RAW_ORDERS` y `RAW_INPUT_METRICS` (no incluido en el repo, te lo entregan junto con el caso):

```bash
# Coloca datos.xlsx en data/ y luego:
python processor.py
```

---

## Decisiones técnicas relevantes

**¿Por qué LangGraph y no agente ReAct para el bot?** Para queries acotadas a un schema conocido, la flexibilidad del agente ReAct no compensa la latencia ni la imprevisibilidad. Un grafo determinista con reintento controlado da 2-3 llamadas al LLM en el caso bueno y nunca entra en loops largos.

**¿Por qué Gemini Flash y no GPT-4 o Claude?** Gratis hasta 15 req/min, suficiente para una demo. El system prompt incluye el schema completo del dataframe para que el modelo no gaste llamadas explorando.

**¿Por qué comparativa pareada en lugar de medias globales?** Con n=46, comparar promedios mezcla zonas, productos y momentos distintos. La pareada controla por contexto: solo compara casos donde la misma dirección y producto existen en ambas plataformas. Los hallazgos sobreviven tres pruebas independientes (IC bootstrap + t-test + Wilcoxon).

**¿Por qué z-score por grupo en benchmarking?** Comparar zonas de distintos países o ZONE_TYPE sin normalizar es injusto. Cada zona se compara solo contra sus pares, y la métrica de divergencia es robusta a la escala de cada métrica.

---

## Costos estimados

Gemini Flash es gratis hasta 15 req/min. Una sesión típica de 10 preguntas al bot consume ~30 llamadas (3 por pregunta). El reporte ejecutivo no usa LLM (todo es estadística pura). El chatbot de oportunidades suma 1 llamada por turno.

---

## Limitaciones conocidas

- **Prueba 1:** scraping bloqueado parcialmente por algunas plataformas, lo que reduce la muestra a n=46. El análisis usa pareada + IC + dos pruebas no paramétricas precisamente para sostener conclusiones con muestra chica.
- **Prueba 2:** el bot reintenta una vez si el código generado falla. Más allá de eso, devuelve el error legible.
- Los `browser_profile_*` no se suben al repo (~14 GB en total) porque son cache local de Chrome.

---

## Contacto

Para dudas conceptuales sobre el caso: daniel.chain@rappi.com