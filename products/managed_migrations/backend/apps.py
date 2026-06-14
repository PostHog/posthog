from django.apps import AppConfig


class ManagedMigrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.managed_migrations.backend"
    label = "managed_migrations"

    def ready(self) -> None:
        # batch_imports.py holds the BatchImport activity-log receiver (handle_batch_import_change)
        # plus a pre_delete cleanup receiver. They used to wire in via the viewset import; the lazy
        # API router no longer pulls that, so a process that never builds the router (celery, temporal,
        # migrate, shell) would stop logging batch-import activity and skip the delete cleanup. The
        # module is light, so import it directly here.
        from products.managed_migrations.backend.api import batch_imports  # noqa: F401, PLC0415
