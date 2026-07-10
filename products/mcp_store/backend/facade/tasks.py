"""
Celery-task wiring for mcp_store.

Re-exports the beat-scheduled maintenance task that core's scheduler registers.
"""

from products.mcp_store.backend.tasks.tasks import maintain_shared_installations

__all__ = ["maintain_shared_installations"]
