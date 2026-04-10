from django.contrib import admin

from products.mcp_store.backend.models import MCPServer


@admin.register(MCPServer)
class MCPServerAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "oauth_client_id", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at")
