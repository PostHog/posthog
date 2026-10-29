from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.experiments.backend"
    label = "experiments"

    def ready(self) -> None:
        # Registers activity signal receivers after the app registry is ready.
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        import products.experiments.backend.activity_logging  # noqa: F401, PLC0415
        from products.experiments.backend.models.experiment import Experiment  # noqa: PLC0415

        register_mixin_model("experiment", Experiment)
