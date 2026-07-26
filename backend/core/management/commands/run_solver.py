from django.core.management.base import BaseCommand, CommandError

from core.models import AcademicTerm, SolverRun
from core.tasks import run_feasibility_solver


class Command(BaseCommand):
    help = "Run the Phase 3 CP-SAT solver for one AcademicTerm (weighted objective by default)."

    def add_arguments(self, parser):
        parser.add_argument("term_id", type=int, help="AcademicTerm primary key.")
        parser.add_argument(
            "--sync",
            action="store_true",
            help=(
                "Run the solver in-process (no Celery/Redis needed) and block until it's done. "
                "Without this flag, the solve is enqueued as a Celery task and the command "
                "returns immediately — that requires a broker and a running worker."
            ),
        )
        parser.add_argument(
            "--feasibility-only",
            action="store_true",
            help=(
                "Run the Phase 3a hard-constraints-only solver (no weighted objective) instead of "
                "the default Phase 3b weighted optimization. Useful for debugging or regression "
                "testing against 3a behavior."
            ),
        )

    def handle(self, *args, **options):
        try:
            term = AcademicTerm.objects.get(pk=options["term_id"])
        except AcademicTerm.DoesNotExist:
            raise CommandError(f"No AcademicTerm with id={options['term_id']}.")

        feasibility_only = options["feasibility_only"]
        if options["sync"]:
            self._run_sync(term, feasibility_only)
        else:
            self._run_async(term, feasibility_only)

    def _run_sync(self, term, feasibility_only):
        result = run_feasibility_solver(term.id, feasibility_only=feasibility_only)
        status = result["status"]

        if status == "FEASIBLE":
            objective_note = ""
            if result.get("objective_value") is not None:
                objective_note = f", objective={result['objective_value']:.2f}"
            self.stdout.write(self.style.SUCCESS(
                f"FEASIBLE — wrote {result['cells_written']} TimetableCell rows"
                f"{objective_note} (SolverRun id={result['solver_run_id']})."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"{status} (SolverRun id={result['solver_run_id']}): "
                f"{result.get('error_message', '(no error message)')}"
            ))

    def _run_async(self, term, feasibility_only):
        solver_run = SolverRun.objects.create(institution=term.institution, term=term, trigger=SolverRun.MANUAL)
        async_result = run_feasibility_solver.delay(term.id, solver_run.id, feasibility_only)
        mode = "feasibility-only" if feasibility_only else "optimized"
        self.stdout.write(
            f"Enqueued Celery task {async_result.id} for term {term.name} ({mode}) "
            f"(SolverRun id={solver_run.id}, status={solver_run.status}). "
            "Requires a running Celery worker connected to the configured broker to actually execute."
        )
