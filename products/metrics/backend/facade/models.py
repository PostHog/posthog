"""Django models re-exported for the presentation layer.

Presentation must not import `backend.models` directly (strict-mode import
surface is `presentation -> facade`), so the alert models it needs are
re-exported here.
"""

from products.metrics.backend.models import MetricsAlertConfiguration, MetricsAlertEvent

__all__ = [
    "MetricsAlertConfiguration",
    "MetricsAlertEvent",
]
