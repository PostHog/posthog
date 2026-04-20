"""Compatibility shim for error tracking presentation serializers.

Canonical module:
- `products.error_tracking.backend.presentation.external_references`
"""

from products.error_tracking.backend.presentation.external_references import (
    ErrorTrackingExternalReferenceIntegrationSerializer,
    ErrorTrackingExternalReferenceSerializer,
)

__all__ = [
    "ErrorTrackingExternalReferenceIntegrationSerializer",
    "ErrorTrackingExternalReferenceSerializer",
]
