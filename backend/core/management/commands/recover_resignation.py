from django.core.management.base import BaseCommand, CommandError

from core.models import AcademicTerm, SolverRun, Teacher
from core.services.resignation import recover_from_resignation


class Command(BaseCommand):
    help = "Reassign a resigned teacher's schedule in one term to other active, eligible staff."

    def add_arguments(self, parser):
        parser.add_argument("teacher_id", type=int, help="Teacher primary key.")
        parser.add_argument("term_id", type=int, help="AcademicTerm primary key.")
        parser.add_argument(
            "--deactivate",
            action="store_true",
            help=(
                "Mark the teacher inactive first, as its own separate save (not part of the "
                "recovery transaction) -- the teacher really is resigned regardless of whether "
                "an automatic replacement schedule can be found."
            ),
        )

    def handle(self, *args, **options):
        try:
            teacher = Teacher.objects.get(pk=options["teacher_id"])
        except Teacher.DoesNotExist:
            raise CommandError(f"No teacher with id={options['teacher_id']}.")

        try:
            term = AcademicTerm.objects.get(pk=options["term_id"])
        except AcademicTerm.DoesNotExist:
            raise CommandError(f"No AcademicTerm with id={options['term_id']}.")

        if options["deactivate"]:
            if teacher.is_active:
                teacher.is_active = False
                teacher.save(update_fields=["is_active"])
        elif teacher.is_active:
            raise CommandError(
                f"{teacher.name} is still active. Pass --deactivate to mark them resigned first, "
                "or deactivate them (e.g. via the admin) before running this command."
            )

        try:
            result = recover_from_resignation(teacher, term)
        except ValueError as exc:
            raise CommandError(str(exc))

        solver_run = (
            SolverRun.objects.filter(term=term, trigger=SolverRun.RESIGNATION_RECOVERY)
            .order_by("-created_at")
            .first()
        )
        run_note = f" (SolverRun id={solver_run.id})" if solver_run else ""

        if result.status == "FEASIBLE":
            self.stdout.write(self.style.SUCCESS(
                f"FEASIBLE — reassigned {len(result.assignments)} TimetableCell rows for "
                f"{teacher.name}'s former CourseRequirements in {term.name}{run_note}."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"{result.status}{run_note}: {result.error_message or '(no error message)'}. "
                "No changes were made — the term is unchanged."
            ))
