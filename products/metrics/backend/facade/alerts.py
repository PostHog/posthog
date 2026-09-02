"""Alerting surface of the metrics facade.

Presentation imports alert-destination constants and alert models through this
module (and `facade.models`) so the strict-mode import surface stays
`presentation -> facade` only. The constants themselves live in
`backend/alert_destinations.py`; the models in `backend/models.py`.
"""

from products.metrics.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    METRICS_ALERT_EVENT_IDS,
    METRICS_ALERT_SLACK_CONTEXT_ELEMENTS,
    METRICS_DESTINATION_TYPES,
)

__all__ = [
    "EVENT_KIND_CONFIG",
    "EVENT_KINDS",
    "METRICS_ALERT_EVENT_IDS",
    "METRICS_ALERT_SLACK_CONTEXT_ELEMENTS",
    "METRICS_DESTINATION_TYPES",
]
