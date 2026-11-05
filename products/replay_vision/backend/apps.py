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
            observation_notes,
        )
        from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT  # noqa: PLC0415
        from products.signals.backend.facade.source_scouts import register_source_scout_refresher  # noqa: PLC0415

        register_source_scout_refresher(
            SCOUT_SOURCE_PRODUCT, "products.replay_vision.backend.scout_template_sync.refresh_template_scout"
        )
