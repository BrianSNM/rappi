#!/usr/bin/env bash
set -e

PROJECT_DIR="/home/brian/Projects/Rappi"

mkdir -p "$PROJECT_DIR"/{src,config,scripts,data/raw,data/screenshots,data/cache,browser_profile}
cd "$PROJECT_DIR"

touch src/__init__.py

cat > .gitignore <<'EOF'
__pycache__/
*.pyc
.venv/
venv/
.env
data/raw/*
data/screenshots/*
data/cache/*
browser_profile/
.DS_Store
*.log
EOF

cat > .env.example <<'EOF'
GEMINI_API_KEY=tu_api_key_aqui
CHROME_BINARY=/usr/bin/google-chrome
CHROME_PROFILE_PATH=/home/brian/.config/google-chrome
CHROME_DEBUG_PORT=9222
SCRAPE_START_HOUR=12
SCRAPE_END_HOUR=20
EOF

cat > requirements.txt <<'EOF'
playwright==1.47.0
google-generativeai==0.8.3
pydantic==2.9.2
numpy==2.1.2
pandas==2.2.3
python-dotenv==1.0.1
streamlit==1.39.0
pydeck==0.9.1
EOF

echo "Estructura creada en $PROJECT_DIR"
echo ""
echo "Siguientes pasos:"
echo "  1. cd $PROJECT_DIR"
echo "  2. python3 -m venv .venv && source .venv/bin/activate"
echo "  3. pip install -r requirements.txt"
echo "  4. playwright install chromium"
echo "  5. cp .env.example .env  # luego edita con tu GEMINI_API_KEY"
