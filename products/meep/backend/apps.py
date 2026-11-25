from django.apps import AppConfig


class MeepConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.meep.backend"
    label = "meep"

    def ready(self) -> None:
        from products.meep.backend import task_profiles  # noqa: PLC0415
        from products.meep.backend.chat import run_saved  # noqa: PLC0415
        from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save  # noqa: PLC0415

        task_profiles.register()
        connect_task_run_post_save(run_saved, dispatch_uid="meep.run_saved")
