from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Tabilo Core"

    def ready(self):
        # Import signal handlers so they register on app startup.
        import core.signals  # noqa: F401
