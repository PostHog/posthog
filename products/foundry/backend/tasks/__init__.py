# Re-export tasks for Celery autodiscover
from products.foundry.backend.tasks.tasks import foundry_attempt_gate_task

__all__ = ["foundry_attempt_gate_task"]
