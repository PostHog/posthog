from django.apps import AppConfig


class ManagedMigrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.managed_migrations.backend"
    label = "managed_migrations"

    def ready(self) -> None:
        # The BatchImport activity-log receiver and pre_delete cleanup receiver used to wire in
        # via the viewset import; the lazy API router no longer pulls that, so a process that
        # never builds the router (celery, temporal, migrate, shell) would stop logging
        # batch-import activity and skip the delete cleanup. They live in activity_logging.py,
        # which has no API/query-runner imports, so wiring them here is cheap.
        from products.managed_migrations.backend import activity_logging  # noqa: F401, PLC0415
