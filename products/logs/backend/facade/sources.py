"""Facade for cloud provider log sources.

The sources viewset is a ModelViewSet over ``LogsSource``, so it needs the model class
itself for its serializer and queryset. Delivery health comes through here too, so the
ClickHouse read stays out of the presentation layer.
"""

from products.logs.backend.models import LogsSource, LogsSourceProvider
from products.logs.backend.source_health import (
    NO_DELIVERIES,
    LogsSourceHealthStatus,
    SourceHealth,
    fetch_sources_health,
)

__all__ = [
    "NO_DELIVERIES",
    "LogsSource",
    "LogsSourceHealthStatus",
    "LogsSourceProvider",
    "SourceHealth",
    "fetch_sources_health",
]
