"""Django app configuration for replay_vision."""

from django.apps import AppConfig


class ReplayVisionConfig(AppConfig):
    name = "products.replay_vision.backend"
    label = "replay_vision"

    def ready(self) -> None:
        # Temporal workers and commands write scanners too, so the receivers connect in every process.
        from products.replay_vision.backend import (  # noqa: F401, PLC0415
            activity_logging,
            experiment_launch,
            media_expiry,
            search_suggestion_cleanup,
        )
