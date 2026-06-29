from django.contrib import admin
from django.utils.html import format_html

from products.warehouse_sources.backend.models.custom_oauth2_integration import CustomOAuth2Integration


@admin.register(CustomOAuth2Integration)
class CustomOAuth2IntegrationAdmin(admin.ModelAdmin):
    list_select_related = ("team", "created_by", "external_data_source")
    list_display = ("id", "team_link", "external_data_source", "has_errors", "created_by", "created_at")
    list_display_links = ("id",)
    list_filter = (("created_at", admin.DateFieldListFilter),)
    search_fields = ("id", "team__name", "team__organization__name", "external_data_source__id")
    ordering = ("-created_at",)
    # All FKs are read-only here, which also keeps Django from rendering a <select> that would load the
    # whole target table per row (CLAUDE.md FK-widget rule).
    readonly_fields = ("id", "team", "external_data_source", "created_by", "created_at", "updated_at")

    # `sensitive_config` (client_secret + tokens) is deliberately omitted from every fieldset — redaction
    # by omission, like IntegrationAdmin. It must never be rendered, even read-only.
    fieldsets = [
        (
            None,
            {
                "fields": ["id", "team", "external_data_source", "created_by", "created_at", "updated_at"],
            },
        ),
        (
            "Config",
            {
                "fields": ["config", "errors"],
            },
        ),
    ]

    # Inspection-only. The row holds OAuth2 secrets and is written solely by the sync worker
    # (refresh_and_persist) under a row lock + team scope; editing it from admin would bypass that scope
    # and crash ModelActivityMixin's update diff (which re-queries through the fail-closed manager with no
    # request context). Reconnect/edit flows live in the product UI.
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="Team")
    def team_link(self, obj: CustomOAuth2Integration) -> str:
        return format_html("{} ({})", obj.team.name, obj.team_id)

    @admin.display(description="Errors", boolean=True)
    def has_errors(self, obj: CustomOAuth2Integration) -> bool:
        return bool(obj.errors)
