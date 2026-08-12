from django.apps import AppConfig
from django.conf import settings


class McpStoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.mcp_store.backend"
    label = "mcp_store"
    verbose_name = "MCP STORE"

    def ready(self) -> None:
        # Deferred: task modules pull in models, which can't import until the app registry is ready.
        from products.mcp_store.backend.tasks.tasks import queue_sync_mcp_server_templates  # noqa: PLC0415

        # Skip during tests (suites sync the catalog explicitly where needed) and during
        # collectstatic (STATIC_COLLECTION=1 in Dockerfile) — no Redis available at build time.
        if not settings.TEST and not settings.STATIC_COLLECTION:
            queue_sync_mcp_server_templates()
