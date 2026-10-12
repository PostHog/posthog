# Celery autodiscovery imports this package, so it must import the task modules.
from products.metrics.backend.tasks.tasks import finalize_metrics_dashboard_import

__all__ = ["finalize_metrics_dashboard_import"]
