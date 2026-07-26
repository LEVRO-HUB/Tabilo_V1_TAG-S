import datetime

from django.core.management.base import BaseCommand, CommandError

from core.models import Institution
from core.services.calendar import generate_calendar


class Command(BaseCommand):
    help = "Generate AcademicCalendarDay rows mapping real dates to day_identifier for an institution."

    def add_arguments(self, parser):
        parser.add_argument("institution_id", type=int, help="Institution primary key.")
        parser.add_argument("start_date", type=str, help="YYYY-MM-DD")
        parser.add_argument("end_date", type=str, help="YYYY-MM-DD")
        parser.add_argument(
            "--weekly-off",
            type=int,
            nargs="+",
            default=[6],
            metavar="WEEKDAY",
            help="Weekday ints that are routine off days (0=Monday..6=Sunday), space-separated. Default: 6 (Sunday).",
        )
        parser.add_argument(
            "--holiday",
            type=str,
            nargs="+",
            default=[],
            metavar="YYYY-MM-DD:Label",
            help=(
                "One or more 'YYYY-MM-DD:Label' pairs, space-separated (label optional, defaults to "
                "'Holiday' if omitted). Quote entries whose label contains spaces."
            ),
        )

    def handle(self, *args, **options):
        try:
            institution = Institution.objects.get(pk=options["institution_id"])
        except Institution.DoesNotExist:
            raise CommandError(f"No institution with id={options['institution_id']}.")

        start_date = self._parse_date(options["start_date"], "start_date")
        end_date = self._parse_date(options["end_date"], "end_date")
        if end_date < start_date:
            raise CommandError(f"end_date ({end_date}) is before start_date ({start_date}).")

        for weekday in options["weekly_off"]:
            if not (0 <= weekday <= 6):
                raise CommandError(f"--weekly-off values must be 0-6 (Monday=0..Sunday=6); got {weekday}.")

        holiday_dates = {}
        for entry in options["holiday"]:
            date_part, _, label_part = entry.partition(":")
            holiday_date = self._parse_date(date_part, f"--holiday entry {entry!r}")
            holiday_dates[holiday_date] = label_part or "Holiday"

        try:
            rows = generate_calendar(
                institution, start_date, end_date,
                weekly_off_weekdays=options["weekly_off"], holiday_dates=holiday_dates,
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f"Generated/updated {len(rows)} AcademicCalendarDay rows for {institution.name} "
            f"({start_date} to {end_date})."
        ))

    def _parse_date(self, value, field_label):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            raise CommandError(f"Invalid date for {field_label}: {value!r}. Expected YYYY-MM-DD.")
