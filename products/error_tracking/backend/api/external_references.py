"""Compatibility shim for external reference API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.external_references import (
    ErrorTrackingExternalReferenceIntegrationSerializer,
    ErrorTrackingExternalReferenceSerializer,
    ErrorTrackingExternalReferenceViewSet,
)

__all__ = [
    "ErrorTrackingExternalReferenceIntegrationSerializer",
    "ErrorTrackingExternalReferenceSerializer",
    "ErrorTrackingExternalReferenceViewSet",
]
