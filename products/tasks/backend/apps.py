from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.tasks.backend"
    label = "tasks"

    def ready(self):
        # Activity-log receivers live in their own import-light module so every
        # process type (celery, temporal, migrate) wires them without pulling
        # the viewset import graph into django.setup().
        from products.tasks.backend import activity_logging  # noqa: F401, PLC0415
