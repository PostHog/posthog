from django.contrib import admin
from django.http import HttpRequest

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

    def get_readonly_fields(self, request: HttpRequest, obj: TeamWorkflowsConfig | None = None) -> tuple[str, ...]:
        return ("team",) if obj is not None else ()

    def has_delete_permission(self, request: HttpRequest, obj: TeamWorkflowsConfig | None = None) -> bool:
        return False
