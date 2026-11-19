from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.tasks.backend"
    label = "tasks"

    def ready(self):
        # Signal receivers live in their own import-light modules so every
        # process type (celery, temporal, migrate) wires them without pulling
        # the viewset import graph into django.setup().
        from products.tasks.backend import (  # noqa: F401, PLC0415
            activity_logging,
            search_index,
            task_profiles,
            task_run_sync,
            team_deletion,
        )

        task_profiles.register()
