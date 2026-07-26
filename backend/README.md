# Tabilo — Backend

Django backend for Tabilo: a unified multi-tenant schema serving both School Edition (weekly
Mon-Sat grid) and College Edition (Day 1-6 rotation) from one codebase and one PostgreSQL
database, plus the OR-Tools CP-SAT timetable solver.

See the [repo root README](../README.md) for how this fits alongside `../frontend/`.

## Quick Start (local dev)

### 1. Prerequisites
- Python 3.11+ installed and on PATH
- PostgreSQL 16 installed and running locally (via pgAdmin or CLI)
- Redis, only if you want to run the solver asynchronously via Celery (optional — see below)

### 2. Create the database (in pgAdmin or psql)
```sql
CREATE USER tabilo_user WITH PASSWORD 'your-local-password';
CREATE DATABASE tabilo_dev OWNER tabilo_user;
GRANT ALL PRIVILEGES ON DATABASE tabilo_dev TO tabilo_user;
```

### 3. Set up the Python environment
From inside `backend/`:

**Windows (PowerShell):**
```powershell
.\setup.ps1
```
**Mac/Linux:**
```bash
./setup.sh
```
This creates `.venv/`, installs everything in `requirements.txt`, and copies
`.env.example` to `.env`.

### 4. Edit `.env`
Fill in `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` to match step 2. `REDIS_URL` is only
needed if you're running the solver asynchronously via Celery — the sync path
(`manage.py run_solver <term_id> --sync`) doesn't need Redis at all.

### 5. Build the schema and load sample data
```bash
python manage.py migrate
python manage.py seed_data
```

### 6. Browse it
```bash
python manage.py createsuperuser
python manage.py runserver
```
Then open http://127.0.0.1:8000/admin/

## Re-activating the environment later
Every new terminal session, before running any `python manage.py ...`
command, activate the venv first:
- Windows: `.\.venv\Scripts\Activate.ps1`
- Mac/Linux: `source .venv/bin/activate`

## Running tests
```bash
python manage.py test core
```

## Notable management commands
- `seed_data` — idempotent seed data for a School and a College scenario
- `generate_time_grid <institution_id> [--regenerate]` — build TimeSlot rows from a TimeGridConfig
- `generate_calendar <institution_id> <start> <end> [--weekly-off ...] [--holiday ...]` — map real
  calendar dates to the abstract day_identifier cycle
- `run_solver <term_id> [--sync] [--feasibility-only]` — run the CP-SAT timetable solver

## Project layout
```
manage.py
requirements.txt
config/                  Django project settings, URLs, WSGI/ASGI, Celery app
core/
  models.py              Institution, AcademicTerm, TimeSlot, CourseRequirement,
                          TimetableCell, SolverRun, SolverWeightConfig, etc.
  admin.py, signals.py
  services/               timegrid.py, ingestion.py, calendar.py
  solver/                 build.py (CP-SAT model), apply.py (writes TimetableCell rows)
  tasks.py                Celery task wrapping the solver
  management/commands/    seed_data, generate_time_grid, generate_calendar, run_solver
  migrations/
  tests/
```

## Deployment target
AWS ECS (this backend) + AWS RDS (PostgreSQL) — see the repo root README for the full picture
alongside the frontend's Cloudflare Pages target. Deployment configuration is a later phase.
