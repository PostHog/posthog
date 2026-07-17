"""
Celery-task wiring for endpoints.

Re-exports the beat-scheduled cleanup task (name-pinned) that core's
scheduler registers.
"""

from products.endpoints.backend.tasks import deactivate_stale_materializations

__all__ = ["deactivate_stale_materializations"]
