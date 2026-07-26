# Tabilo — Frontend

Vite + React (JavaScript) frontend for Tabilo. Currently a placeholder — Phase 5b will build out
the actual UI against the Django API in `../backend/`.

## Local dev

```bash
npm install
cp .env.example .env
npm run dev
```

`VITE_API_BASE_URL` in `.env` isn't consumed by any code yet — it's wired in now for Phase 5b.

## Build

```bash
npm run build
```

Produces a static `dist/` folder, deployable as-is (intended target: Cloudflare Pages).
