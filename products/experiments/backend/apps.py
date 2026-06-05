from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.experiments.backend"
    label = "experiments"

    def ready(self) -> None:
        # Registers activity signal receivers after the app registry is ready.
        import products.experiments.backend.activity_logging  # noqa: F401, PLC0415
