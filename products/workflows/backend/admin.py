from django.contrib import admin

from products.workflows.backend.models import TeamWorkflowsConfig


@admin.register(TeamWorkflowsConfig)
class TeamWorkflowsConfigAdmin(admin.ModelAdmin):
    list_display = (
        "team",
        "workflow_task_rate_limit_per_day",
        "workflow_task_team_rate_limit_per_day",
    )
    fields = ("team", "workflow_task_rate_limit_per_day", "workflow_task_team_rate_limit_per_day")
    search_fields = ("team__id", "team__name", "team__organization__name")
    raw_id_fields = ("team",)
    list_select_related = ("team", "team__organization")
