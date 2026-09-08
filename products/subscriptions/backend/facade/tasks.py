"""Public Celery registrations owned by subscriptions."""

from products.subscriptions.backend.tasks import reconcile_proactive_artifact_adoptions

__all__ = ["reconcile_proactive_artifact_adoptions"]
