"""Django app configuration for stamphog."""

from django.apps import AppConfig


class StamphogConfig(AppConfig):
    name = "products.stamphog.backend"
    label = "stamphog"

    def ready(self) -> None:
        # Repo configs are written by webhook Celery tasks too, so the receiver must connect in
        # every process, not only where the API router is built.
        from products.stamphog.backend import activity_logging  # noqa: F401, PLC0415
