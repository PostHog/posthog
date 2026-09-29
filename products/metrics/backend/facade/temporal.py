"""Facade re-exports for the metrics alerting Temporal wiring.

Core registers this product's source evaluation workflow and activity on the shared alerts
platform evaluation queue (``posthog/management/commands/start_temporal_worker.py``). That
wiring crosses the boundary as objects, so re-export exactly what core touches.
"""

from products.metrics.backend.temporal.alert_evaluate import SOURCE_EVALUATION_ACTIVITIES, SOURCE_EVALUATION_WORKFLOWS

__all__ = ["SOURCE_EVALUATION_ACTIVITIES", "SOURCE_EVALUATION_WORKFLOWS"]
