import logging
from contextlib import nullcontext
from typing import cast

from django import forms
from django.contrib import admin, messages
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.models.scoping import team_scope
from posthog.models.user import User
from posthog.storage import object_storage

from .logic.services.ai_run_defaults import validate_ai_run_preferences_payload
from .models import SandboxSnapshot, Task, TaskRun, TeamTasksConfig, UserTasksConfig
from .visibility import task_run_visibility_q, task_visibility_q

logger = logging.getLogger(__name__)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
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

    def get_urls(self) -> list:
        # Prepended so it isn't shadowed by the default `<path:object_id>/` route.
        return [
            path(
                "<uuid:run_id>/download-logs/",
                self.admin_site.admin_view(self.download_logs),
                name="tasks_taskrun_download_logs",
            ),
            *super().get_urls(),
        ]

    def download_logs(self, request: HttpRequest, run_id) -> HttpResponse:
        run = self.get_object(request, run_id)
        if run is None:
            raise Http404("Task run not found")
        if object_storage.head_object(run.log_url) is None:
            self.message_user(
                request,
                "No logs available for this run — they may not have been written yet, or object storage is unreachable.",
                level=messages.WARNING,
            )
            return redirect(reverse("admin:tasks_taskrun_change", args=[run_id]))
        filename = f"run_{run.id}.jsonl"
        url = object_storage.get_presigned_url(
            run.log_url,
            expiration=300,
            content_disposition=f'attachment; filename="{filename}"',
        )
        if not url:
            self.message_user(
                request,
                "Could not generate a download link for this run's logs (object storage unavailable).",
                level=messages.WARNING,
            )
            return redirect(reverse("admin:tasks_taskrun_change", args=[run_id]))
        return HttpResponseRedirect(url)

    @admin.display(description="Logs")
    def download_logs_link(self, obj: TaskRun) -> str:
        if not obj or not obj.pk:
            return "—"
        url = reverse("admin:tasks_taskrun_download_logs", args=[obj.pk])
        return format_html('<a class="button" href="{}">Download logs</a>', url)


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
