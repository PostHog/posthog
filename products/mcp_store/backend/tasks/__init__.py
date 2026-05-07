# Re-export tasks for Celery autodiscover
from products.mcp_store.backend.tasks.tasks import sync_installation_tools_task

__all__ = ["sync_installation_tools_task"]
