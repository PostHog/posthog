"""Compatibility shim for fingerprint API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import ErrorTrackingFingerprintSerializer
from products.error_tracking.backend.presentation.views import ErrorTrackingFingerprintViewSet

__all__ = [
    "ErrorTrackingFingerprintSerializer",
    "ErrorTrackingFingerprintViewSet",
]
