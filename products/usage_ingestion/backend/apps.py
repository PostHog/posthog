"""Django app configuration for usage_ingestion."""

from django.apps import AppConfig


class UsageIngestionConfig(AppConfig):
    name = "products.usage_ingestion.backend"
    label = "usage_ingestion"

    def ready(self) -> None:
        from .tasks import receivers  # noqa: F401, PLC0415 — registers Django signal receivers after app loading
