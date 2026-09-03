from django.contrib import admin
from django.http import HttpRequest
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

    def has_add_permission(self, request: HttpRequest) -> bool:
        # A table created here would have no credential (this form has no way to set one - see
        # readonly_fields) and an unrestricted url_pattern, which is exactly the combination
        # DataWarehouseTable.clean()/save() exist to refuse on every other write path. Those checks
        # can't cover creation (a brand-new row has no prior state to compare against), so the
        # invariant depends entirely on the creator computing url_pattern itself rather than taking
        # it from form input - true for upload/pipeline sync, never true for a raw admin add form.
        return False

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
