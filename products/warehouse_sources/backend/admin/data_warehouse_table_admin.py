from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.warehouse_sources.backend.models import DataWarehouseTable


@admin.register(DataWarehouseTable)
class DataWarehouseTableAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "format",
        "url_pattern",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    readonly_fields = ("credential", "external_data_source")
    ordering = ("-created_at",)

    @admin.display(description="Team")
    def team_link(self, obj: DataWarehouseTable):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[obj.team.pk]),
            obj.team.name,
        )

    @admin.display(description="Organization")
    def organization_link(self, obj: DataWarehouseTable):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[obj.team.organization.pk]),
            obj.team.organization.name,
        )
