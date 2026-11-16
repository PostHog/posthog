from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


@admin.register(ExternalDataSchema)
class ExternalDataSchemaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "should_sync",
        "sync_type",
        "source_type",
        "team_link",
        "last_synced_at",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization", "source")
    list_filter = ("status", "should_sync", "sync_type")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team",)
    raw_id_fields = ("table", "source")
    readonly_fields = ("table", "source", "created_by", "console_link")
    ordering = ("-created_at",)

    @admin.display(description="Partitioning, sync and jobs")
    def console_link(self, schema: ExternalDataSchema) -> SafeString:
        return format_html(
            '<a href="{}?schema={}">Repartition, schedules, syncs and jobs: now in PostHog Admin &#8599;</a>',
            reverse("admin_console_tool", kwargs={"tool_key": "warehouse-sources"}),
            schema.pk,
        )

    @admin.display(description="Team")
    def team_link(self, schema: ExternalDataSchema):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[schema.team.pk]),
            schema.team.name,
        )

    @admin.display(description="Source type")
    def source_type(self, schema: ExternalDataSchema):
        return schema.source.source_type
