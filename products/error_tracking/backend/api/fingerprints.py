"""Compatibility shim for fingerprint API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.fingerprints import (
    ErrorTrackingFingerprintSerializer,
    ErrorTrackingFingerprintViewSet,
)

__all__ = [
    "ErrorTrackingFingerprintSerializer",
    "ErrorTrackingFingerprintViewSet",
]
