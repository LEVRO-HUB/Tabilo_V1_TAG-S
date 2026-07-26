"""
Tabilo — Celery app (Phase 3).

Standard Django/Celery wiring. Broker and result backend both default to a
local Redis instance, overridable via CELERY_BROKER_URL / CELERY_RESULT_BACKEND
env vars (see .env.example). Redis does not need to be running for local
solver testing — see core/management/commands/run_solver.py's --sync flag,
which runs the solver in-process without Celery.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("tabilo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
