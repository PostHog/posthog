from contextlib import nullcontext
from typing import cast

from django import forms
from django.contrib import admin
from django.http import HttpRequest
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.models.scoping import team_scope
from posthog.models.user import User

from .logic.services.ai_run_defaults import validate_ai_run_preferences_payload
from .models import SandboxSnapshot, Task, TaskRun, TeamTasksConfig, UserTasksConfig
from .presentation.views.infrastructure_admin import infrastructure_admin
from .visibility import task_run_visibility_q, task_visibility_q


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    change_list_template = "admin/tasks/task/change_list.html"

    def get_urls(self) -> list:
        return [
            path("infrastructure/", self.admin_site.admin_view(infrastructure_admin), name="tasks_infrastructure"),
            *super().get_urls(),
        ]

    list_display = ("slug", "title", "origin_product", "internal", "team", "created_by", "created_at", "deleted")
    list_filter = ("origin_product", "internal", "deleted", "created_at")
    search_fields = ("title", "description", "repository")
    readonly_fields = ("id", "slug", "task_number", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("team", "created_by", "github_integration", "github_user_integration")

    fieldsets = (
        (None, {"fields": ("id", "slug", "task_number", "title", "description", "origin_product", "internal")}),
        ("Team & User", {"fields": ("team", "created_by")}),
        ("Repository", {"fields": ("github_integration", "github_user_integration", "repository")}),
        ("Schema", {"fields": ("json_schema",)}),
        ("Status", {"fields": ("deleted", "deleted_at")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request: HttpRequest):
        return (
            super()
            .get_queryset(request)
            .filter(team__organization_id__in=cast(User, request.user).organizations.values("id"))
            .filter(task_visibility_q(request.user.id))
        )


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "status", "environment", "stage", "created_at")
    list_filter = ("status", "environment", "created_at")
    search_fields = ("task__title", "branch", "stage")
    readonly_fields = ("id", "created_at", "updated_at", "completed_at", "download_logs_link")
    autocomplete_fields = ("task",)

    fieldsets = (
        (None, {"fields": ("id", "task", "status", "environment", "stage", "branch")}),
        ("Storage", {"fields": ("error_message", "download_logs_link")}),
        ("Data", {"fields": ("output", "state")}),
        ("Dates", {"fields": ("created_at", "updated_at", "completed_at")}),
    )

    def get_queryset(self, request: HttpRequest):
        return (
            super()
            .get_queryset(request)
            .filter(task__team__organization_id__in=cast(User, request.user).organizations.values("id"))
            .filter(task_run_visibility_q(request.user.id))
        )

    @admin.display(description="Logs")
    def download_logs_link(self, obj: TaskRun) -> str:
        if not obj or not obj.pk:
            return "—"
        url = reverse("admin_console_tool_operation", kwargs={"tool_key": "task-run-logs", "operation_key": "download"})
        return format_html('<a href="{}?run={}">Download logs: now in PostHog Admin &#8599;</a>', url, obj.pk)


@admin.register(SandboxSnapshot)
class SandboxSnapshotAdmin(admin.ModelAdmin):
    list_display = ("external_id", "status", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("external_id", "repos")
    readonly_fields = ("id", "external_id", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("id", "external_id", "status")}),
        ("Repository Info", {"fields": ("repos",)}),
        ("Metadata", {"fields": ("metadata",)}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )


class _TasksConfigAdminForm(forms.ModelForm):
    """Shared form for the two tasks-config admins. Runs the same checks as the API
    write path (`update_team_ai_run_preferences` / `update_user_ai_run_preferences`),
    so an admin edit cannot store a payload the resolver would reject or skip."""

    def clean_team(self):
        team = self.cleaned_data["team"]
        # Preference rows are keyed on the canonical (project root) team; a row keyed on an
        # environment team is never read by the resolver.
        if team.parent_team_id is not None:
            raise forms.ValidationError(
                "Preferences are keyed on the project root team. "
                f"Pick the parent team (id {team.parent_team_id}) instead of this environment team."
            )
        return team

    def clean_ai_run_preferences(self):
        prefs = self.cleaned_data.get("ai_run_preferences")
        if not prefs:
            return prefs
        if not isinstance(prefs, dict):
            raise forms.ValidationError("Must be a JSON object.")
        validate_ai_run_preferences_payload(prefs)
        return prefs

    def _post_clean(self) -> None:
        # Unique-constraint validation queries through the model's default manager, which for
        # UserTasksConfig is fail-closed and raises without a team context. Admin requests have
        # none, so scope model validation to the team picked in the form.
        team = self.cleaned_data.get("team")
        with team_scope(team.id) if team is not None else nullcontext():
            super()._post_clean()  # type: ignore[misc]  # django-stubs does not declare _post_clean


@admin.register(TeamTasksConfig)
class TeamTasksConfigAdmin(admin.ModelAdmin):
    form = _TasksConfigAdminForm
    list_display = ("team", "ai_run_preferences", "created_at", "updated_at")
    search_fields = ("team__name", "team__organization__name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("team",)
    list_select_related = ("team",)
    show_full_result_count = False


@admin.register(UserTasksConfig)
class UserTasksConfigAdmin(admin.ModelAdmin):
    form = _TasksConfigAdminForm
    list_display = ("id", "team", "user", "ai_run_preferences", "created_at", "updated_at")
    search_fields = ("team__name", "user__email")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("team", "user")
    show_full_result_count = False

    def get_queryset(self, request: HttpRequest):
        # Admin has no team context; UserTasksConfig's default manager is fail-closed.
        return UserTasksConfig.objects.unscoped().select_related("team", "user")
