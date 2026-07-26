"""
Tabilo — Celery tasks (Phase 3).

run_feasibility_solver is the async entry point for the CP-SAT solver: a
thin wrapper around core.solver.build.solve_optimized (or solve_feasibility
when feasibility_only=True) + core.solver.apply.apply_solution that turns
solver outcomes into SolverRun status updates instead of letting a failure
vanish into worker logs. The name predates Phase 3b's weighted objective
becoming the default behavior — kept as-is to avoid churning every caller
for a rename; feasibility_only is what actually selects Phase 3a behavior.

Calling this function directly (not via .delay()/.apply_async()) runs it
synchronously in-process without touching the Celery broker at all — that's
what `manage.py run_solver <term_id> --sync` does, so local solver testing
never requires Redis to be running.

solver_run_id is optional and exists for the enqueue-and-return-immediately
path: `run_solver` (without --sync) needs to print a SolverRun id right
after enqueueing, before any worker has necessarily picked the task up, so
it pre-creates the PENDING row itself and passes its id through rather than
letting this task create its own — otherwise a caller with no worker running
would have nothing to print. The --sync path and any direct/test call omit
it and get a fresh row created here instead.
"""

from celery import shared_task
from django.utils import timezone

from core.models import AcademicTerm, SolverRun
from core.solver.apply import apply_solution
from core.solver.build import solve_feasibility, solve_optimized


@shared_task(bind=True)
def run_feasibility_solver(self, term_id, solver_run_id=None, feasibility_only=False):
    term = AcademicTerm.objects.get(pk=term_id)

    if solver_run_id is not None:
        solver_run = SolverRun.objects.get(pk=solver_run_id)
    else:
        solver_run = SolverRun.objects.create(institution=term.institution, term=term, trigger=SolverRun.MANUAL)

    solver_run.status = SolverRun.RUNNING
    solver_run.celery_task_id = self.request.id or ""
    solver_run.started_at = timezone.now()
    solver_run.save(update_fields=["status", "celery_task_id", "started_at"])

    try:
        result = solve_feasibility(term) if feasibility_only else solve_optimized(term)
        if result.status not in ("FEASIBLE", "OPTIMAL"):
            solver_run.status = SolverRun.FAILED
            solver_run.error_message = result.error_message or f"Solver returned {result.status}."
            solver_run.finished_at = timezone.now()
            solver_run.save(update_fields=["status", "error_message", "finished_at"])
            return {"solver_run_id": solver_run.id, "status": result.status}

        cells_written = apply_solution(term, result.assignments)
        solver_run.status = SolverRun.SUCCESS
        solver_run.objective_value = result.objective_value
        solver_run.finished_at = timezone.now()
        solver_run.save(update_fields=["status", "objective_value", "finished_at"])
        return {
            "solver_run_id": solver_run.id,
            "status": result.status,
            "cells_written": cells_written,
            "objective_value": result.objective_value,
        }

    except Exception as exc:
        solver_run.status = SolverRun.FAILED
        solver_run.error_message = str(exc)
        solver_run.finished_at = timezone.now()
        solver_run.save(update_fields=["status", "error_message", "finished_at"])
        return {"solver_run_id": solver_run.id, "status": "ERROR", "error_message": str(exc)}
