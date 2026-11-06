"""Facade re-export for the MCP registry Celery surface.

Core's central beat wiring (``posthog/tasks/scheduled.py``) registers the sync sweep from
here rather than reaching into the product's internals, and the management command runs the
same pipeline through this boundary. Lives apart from ``api.py`` so the task modules' heavy
imports (celery, posthoganalytics) stay off that module, which presentation imports on every
request.
"""

from products.mcp_registry.backend.tasks.tasks import (
    MCP_REGISTRY_SYNC_CRONTAB,
    is_pipeline_enabled,
    run_mcp_registry_sync,
    run_sync_pipeline,
)

__all__ = [
    "MCP_REGISTRY_SYNC_CRONTAB",
    "is_pipeline_enabled",
    "run_mcp_registry_sync",
    "run_sync_pipeline",
]
