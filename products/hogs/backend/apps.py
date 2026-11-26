"""Django app configuration for hogs."""

from django.apps import AppConfig


class HogsConfig(AppConfig):
    name = "products.hogs.backend"
    label = "hogs"

    def ready(self) -> None:
        from products.hogs.backend import task_profiles  # noqa: PLC0415

        task_profiles.register()

        # Declared by task name, so nothing here imports the task while Django is still starting.
        from celery.schedules import crontab  # noqa: PLC0415

        from posthog.celery import app  # noqa: PLC0415

        app.conf.beat_schedule["fire due hog schedules"] = {
            "task": "products.hogs.backend.tasks.tasks.fire_due_hog_schedules",
            "schedule": crontab(minute="*"),
            # A run that starts late is dropped, because the next minute's run covers the same schedules.
            "options": {"expires": 90},
        }
