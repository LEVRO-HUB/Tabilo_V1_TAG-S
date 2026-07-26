from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.models import Institution
from core.services.timegrid import generate_time_slots


class Command(BaseCommand):
    help = "Generate TimeSlot rows for an institution from its TimeGridConfig."

    def add_arguments(self, parser):
        parser.add_argument("institution_id", type=int, help="Institution primary key.")
        parser.add_argument(
            "--regenerate",
            action="store_true",
            help=(
                "Delete and rebuild existing time slots from the current TimeGridConfig. "
                "Refuses if any TimetableCell still references the existing slots."
            ),
        )

    def handle(self, *args, **options):
        try:
            institution = Institution.objects.get(pk=options["institution_id"])
        except Institution.DoesNotExist:
            raise CommandError(f"No institution with id={options['institution_id']}.")

        try:
            slots = generate_time_slots(institution, regenerate=options["regenerate"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages))

        self.stdout.write(self.style.SUCCESS(f"Generated {len(slots)} time slots for {institution.name}."))
