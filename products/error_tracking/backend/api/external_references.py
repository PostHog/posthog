"""Compatibility shim for external reference API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import (
    ErrorTrackingExternalReferenceIntegrationSerializer,
    ErrorTrackingExternalReferenceSerializer,
)
from products.error_tracking.backend.presentation.views import ErrorTrackingExternalReferenceViewSet

__all__ = [
    "ErrorTrackingExternalReferenceIntegrationSerializer",
    "ErrorTrackingExternalReferenceSerializer",
    "ErrorTrackingExternalReferenceViewSet",
]
