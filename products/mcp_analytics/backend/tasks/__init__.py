# Re-export tasks for Celery autodiscover. autodiscover_tasks() imports the
# `tasks` package (this __init__.py), not its submodules, so any @shared_task
# defined inside `tasks/tasks.py` needs to be re-exported here to be visible
# to the worker.
from products.mcp_analytics.backend.tasks.tasks import compute_intent_clusters

__all__ = ["compute_intent_clusters"]
