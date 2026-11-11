"""Django app configuration for release."""

from django.apps import AppConfig


class ReleaseConfig(AppConfig):
    name = "products.release.backend"
    label = "release"

    def ready(self) -> None:
        from products.feature_flags.backend.facade.release_candidates import on_flag_created  # noqa: PLC0415

        from .tasks import queue_release_for_new_flag  # noqa: PLC0415

        on_flag_created(queue_release_for_new_flag)
