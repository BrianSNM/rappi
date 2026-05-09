#!/usr/bin/env bash
set -e
mkdir -p data/raw data/screenshots data/cache browser_profile
touch src/__init__.py
echo "Listo. Ahora copia requirements.txt, .env.example y .gitignore a este directorio."
