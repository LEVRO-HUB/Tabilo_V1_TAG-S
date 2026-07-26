# Tabilo

Multi-tenant timetable SaaS for schools and colleges: a Django backend with an OR-Tools CP-SAT
solver, and a React frontend, deployed separately.

```
backend/    Django + PostgreSQL + Celery/OR-Tools — see backend/README.md
frontend/   Vite + React (placeholder for now) — see frontend/README.md
```

## Backend

Django REST-ish app (admin-driven for now), targeting PostgreSQL. Full setup instructions,
management commands, and project layout: **[backend/README.md](backend/README.md)**.

```bash
cd backend
./setup.sh   # or .\setup.ps1 on Windows
```

## Frontend

Vite + React (JavaScript). Currently a placeholder — Phase 5b will build out the real UI against
the backend's API. Full instructions: **[frontend/README.md](frontend/README.md)**.

```bash
cd frontend
npm install
npm run dev
```

## Deployment targets

Backend → AWS ECS · Frontend → Cloudflare Pages · Database → AWS RDS (PostgreSQL). Deployment
configuration itself is a later phase — this repo structure just separates the two halves so they
can ship independently.
