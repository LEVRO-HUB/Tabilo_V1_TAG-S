# Tabilo local setup (Windows PowerShell)
# Usage: right-click this file > "Run with PowerShell", or from a terminal:
#        powershell -ExecutionPolicy Bypass -File setup.ps1

Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Cyan
python -m venv .venv

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& .\.venv\Scripts\Activate.ps1

Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Cyan
pip install -r requirements.txt   # installs Django, psycopg (v3), python-dotenv

if (-Not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example (edit this with your local Postgres credentials!)" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
} else {
    Write-Host ".env already exists, leaving it as-is." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Edit .env with your Postgres username/password/db name"
Write-Host "  2. python manage.py migrate"
Write-Host "  3. python manage.py seed_data"
Write-Host ""
Write-Host "Next time you open a new terminal, activate the venv first with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
