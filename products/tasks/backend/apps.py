from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.tasks.backend"
    label = "tasks"

    def ready(self):
        # Signal receivers live in their own import-light modules so every
        # process type (celery, temporal, migrate) wires them without pulling
        # the viewset import graph into django.setup().
        from products.tasks.backend import activity_logging, search_index, team_deletion  # noqa: F401, PLC0415
