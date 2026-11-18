from django.apps import AppConfig


class McpRegistryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.mcp_registry.backend"
    label = "mcp_registry"
    verbose_name = "MCP REGISTRY"
