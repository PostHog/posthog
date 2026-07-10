# Re-export tasks for Celery autodiscover
from products.mcp_store.backend.tasks.tasks import maintain_shared_installations, sync_installation_tools_task

__all__ = ["maintain_shared_installations", "sync_installation_tools_task"]
