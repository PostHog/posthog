"""Django app configuration for stamphog."""

from django.apps import AppConfig


class StamphogConfig(AppConfig):
    name = "products.stamphog.backend"
    label = "stamphog"

    def ready(self) -> None:
        # Repo configs are written by webhook Celery tasks too, so the receiver must connect in
        # every process, not only where the API router is built.
        from products.stamphog.backend import (  # noqa: F401, PLC0415
            activity_logging,
            slack_actions,
            slack_channel_messages,
        )

        slack_actions.connect()
        slack_channel_messages.connect()
