#!/usr/bin/env bash
# Tabilo local setup (Mac/Linux)
# Usage: chmod +x setup.sh && ./setup.sh

set -e

echo "Creating virtual environment (.venv)..."
python3 -m venv .venv

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt   # installs Django, psycopg (v3), python-dotenv

if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example (edit this with your local Postgres credentials!)"
    cp .env.example .env
else
    echo ".env already exists, leaving it as-is."
fi

echo ""
echo "Setup complete."
echo "Next steps:"
echo "  1. Edit .env with your Postgres username/password/db name"
echo "  2. python manage.py migrate"
echo "  3. python manage.py seed_data"
echo ""
echo "Next time you open a new terminal, activate the venv first with:"
echo "  source .venv/bin/activate"
