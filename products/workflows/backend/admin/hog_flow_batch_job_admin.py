from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob


@admin.register(HogFlowBatchJob)
class HogFlowBatchJobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "hog_flow_link", "team_link", "created_at")
    list_filter = (
        ("status", admin.ChoicesFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    )
    list_select_related = ("team", "hog_flow")
    search_fields = ("hog_flow__name", "team__name", "team__organization__name")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "team",
        "team_link",
        "hog_flow",
        "hog_flow_link",
        "created_by",
        "created_at",
        "updated_at",
        "variables",
        "filters",
    )
    fields = (
        "status",
        "team_link",
        "hog_flow_link",
        "created_by",
        "created_at",
        "updated_at",
        "variables",
        "filters",
    )

    @admin.display(description="Team")
    def team_link(self, batch_job: HogFlowBatchJob):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[batch_job.team.pk]),
            batch_job.team.name,
        )

    @admin.display(description="Hog flow")
    def hog_flow_link(self, batch_job: HogFlowBatchJob):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:workflows_hogflow_change", args=[batch_job.hog_flow.pk]),
            batch_job.hog_flow.name or batch_job.hog_flow.pk,
        )
