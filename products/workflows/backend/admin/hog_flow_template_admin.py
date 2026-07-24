from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate


@admin.register(HogFlowTemplate)
class HogFlowTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "scope", "team_link", "created_at")
    list_filter = (
        ("scope", admin.ChoicesFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    )
    list_select_related = ("team",)
    search_fields = ("name", "team__name", "team__organization__name")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "team",
        "team_link",
        "created_by",
        "created_at",
        "updated_at",
        "trigger",
        "trigger_masking",
        "conversion",
        "edges",
        "actions",
        "variables",
    )
    fields = (
        "name",
        "description",
        "image_url",
        "tags",
        "scope",
        "exit_condition",
        "abort_action",
        "team_link",
        "created_by",
        "created_at",
        "updated_at",
        "trigger",
        "trigger_masking",
        "conversion",
        "edges",
        "actions",
        "variables",
    )

    @admin.display(description="Team")
    def team_link(self, template: HogFlowTemplate):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[template.team.pk]),
            template.team.name,
        )
