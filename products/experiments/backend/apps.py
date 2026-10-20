from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.experiments.backend"
    label = "experiments"

    def ready(self) -> None:
        # Registers activity signal receivers after the app registry is ready.
        import products.experiments.backend.activity_logging  # noqa: F401, PLC0415
        from products.experiments.backend import task_profiles  # noqa: PLC0415
        from products.tasks.backend.facade.profiles import register_task_profiles  # noqa: PLC0415

        register_task_profiles(task_profiles.PROFILES)
