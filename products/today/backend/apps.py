"""Django app configuration for today."""

from django.apps import AppConfig

from . import task_profiles


class TodayConfig(AppConfig):
    name = "products.today.backend"
    label = "today"

    def ready(self) -> None:
        task_profiles.register()
