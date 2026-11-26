"""Django app configuration for release."""

from django.apps import AppConfig


class ReleaseConfig(AppConfig):
    name = "products.release.backend"
    label = "release"

    def ready(self) -> None:
        from products.feature_flags.backend.facade.release_candidates import on_active_flag_saved  # noqa: PLC0415

        from .tasks.tasks import queue_release_for_new_flag  # noqa: PLC0415

        on_active_flag_saved(queue_release_for_new_flag)
