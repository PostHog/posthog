from django.apps import AppConfig


class McpEventsConfig(AppConfig):
    name = "products.mcp_events.backend"
    label = "mcp_events"

    def ready(self) -> None:
        from products.mcp_events.backend import signals  # noqa: F401, PLC0415 — registers receivers after model loading
