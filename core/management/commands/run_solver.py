from django.core.management.base import BaseCommand, CommandError

from core.models import AcademicTerm, SolverRun
from core.tasks import run_feasibility_solver


class Command(BaseCommand):
    help = "Run the Phase 3a CP-SAT feasibility solver for one AcademicTerm."

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

    def handle(self, *args, **options):
        try:
            term = AcademicTerm.objects.get(pk=options["term_id"])
        except AcademicTerm.DoesNotExist:
            raise CommandError(f"No AcademicTerm with id={options['term_id']}.")

        if options["sync"]:
            self._run_sync(term)
        else:
            self._run_async(term)

    def _run_sync(self, term):
        result = run_feasibility_solver(term.id)
        status = result["status"]

        if status == "FEASIBLE":
            self.stdout.write(self.style.SUCCESS(
                f"FEASIBLE — wrote {result['cells_written']} TimetableCell rows "
                f"(SolverRun id={result['solver_run_id']})."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"{status} (SolverRun id={result['solver_run_id']}): "
                f"{result.get('error_message', '(no error message)')}"
            ))

    def _run_async(self, term):
        solver_run = SolverRun.objects.create(institution=term.institution, term=term)
        async_result = run_feasibility_solver.delay(term.id, solver_run.id)
        self.stdout.write(
            f"Enqueued Celery task {async_result.id} for term {term.name} "
            f"(SolverRun id={solver_run.id}, status={solver_run.status}). "
            "Requires a running Celery worker connected to the configured broker to actually execute."
        )
