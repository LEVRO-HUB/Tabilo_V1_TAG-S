# Tabilo — Phase 1 (Core Database Basement)

Unified multi-tenant Django schema for Tabilo, serving both School Edition
(weekly Mon-Sat grid) and College Edition (Day 1-6 rotation) from one
codebase and one PostgreSQL database.

## Quick Start (local dev)

### 1. Prerequisites
- Python 3.11+ installed and on PATH
- PostgreSQL 16 installed and running locally (via pgAdmin or CLI)

### 2. Create the database (in pgAdmin or psql)
```sql
CREATE USER tabilo_user WITH PASSWORD 'your-local-password';
CREATE DATABASE tabilo_dev OWNER tabilo_user;
GRANT ALL PRIVILEGES ON DATABASE tabilo_dev TO tabilo_user;
```

### 3. Set up the Python environment
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
Fill in `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` to match step 2.

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

## Project layout
```
manage.py
requirements.txt
config/          Django project settings, URLs, WSGI/ASGI
core/            Phase 1 models, admin, signals, seed_data command
  models.py      Institution, Department, AcademicTerm, Teacher, Subject,
                 ClassDivision, TimeSlot, ElectiveGroup, CourseRequirement,
                 FacultyDutyBlock, TimetableCell
  signals.py     Default department creation, single-active-term
                 enforcement, teacher workload-cap enforcement
  management/commands/seed_data.py
                 Idempotent seed data for a School and a College scenario
```
