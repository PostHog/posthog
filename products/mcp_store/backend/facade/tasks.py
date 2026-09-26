"""Facade re-export for the MCP store Celery surface.

Core's central beat wiring (``posthog/tasks/scheduled.py``) registers the catalog sync from
here rather than reaching into the product's internals. Lives apart from ``api.py`` so the
task module's heavy imports (celery, redis) stay off that module, which presentation imports
on every request.
"""

from products.mcp_store.backend.tasks.tasks import MCP_STORE_CATALOG_SYNC_CRONTAB, sync_mcp_server_templates_task

__all__ = [
    "MCP_STORE_CATALOG_SYNC_CRONTAB",
    "sync_mcp_server_templates_task",
]
