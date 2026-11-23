from typing import Any

from django.apps import AppConfig

from celery.signals import worker_ready


def queue_catalog_sync_when_worker_is_ready(**kwargs: Any) -> None:
    # Deferred: task modules pull in models, which can't import until the app registry is ready.
    from products.mcp_store.backend.tasks.tasks import queue_sync_mcp_server_templates  # noqa: PLC0415

    queue_sync_mcp_server_templates()


class McpStoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.mcp_store.backend"
    label = "mcp_store"
    verbose_name = "MCP STORE"

    def ready(self) -> None:
        # Only a Celery worker queues the catalog sync, once it is ready. Every other process that
        # loads Django (web, Dagster runs, management commands) may hold different broker settings,
        # and a task it queues onto another broker is never run. Workers start with every deploy, and
        # tests, collectstatic and other one-off commands never send worker_ready.
        worker_ready.connect(queue_catalog_sync_when_worker_is_ready, dispatch_uid="mcp_store_catalog_sync")
