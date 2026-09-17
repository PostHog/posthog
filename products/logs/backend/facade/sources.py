"""Facade re-exports for cloud provider log sources.

The sources viewset is a ModelViewSet over ``LogsSource``, so it needs the model class
itself for its serializer and queryset.
"""

from products.logs.backend.models import LogsSource, LogsSourceProvider

__all__ = ["LogsSource", "LogsSourceProvider"]
