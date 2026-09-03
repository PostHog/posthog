import logging
from typing import cast

from django import forms
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.models.scoping import team_scope
from posthog.models.user import User
from posthog.storage import object_storage

from . import loop_service
from .logic.services.ai_run_defaults import validate_ai_run_preferences
from .loop_lifecycle import DISABLED_REASON_ADMIN_PAUSED, pause_loop
from .models import Loop, LoopTrigger, SandboxSnapshot, Task, TaskRun, TeamTasksConfig, UserTasksConfig
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


@admin.register(Loop)
class LoopAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "visibility",
        "enabled",
        "team",
        "created_by",
        "last_run_at",
        "last_run_status",
        "consecutive_failures",
        "deleted",
    )
    list_filter = ("visibility", "enabled", "deleted", "overlap_policy", "runtime_adapter")
    search_fields = ("name", "description")
    readonly_fields = (
        "id",
        "enabled",
        "last_run_at",
        "last_run_status",
        "last_error",
        "consecutive_failures",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("team", "created_by", "creator")
    raw_id_fields = ("sandbox_environment",)
    actions = ["pause_loops"]

    def get_queryset(self, request: HttpRequest):
        # Admin has no team context; Loop's default manager is fail-closed.
        return Loop.objects.unscoped().select_related("team", "created_by")

    @admin.action(description="Pause selected loops")
    def pause_loops(self, request: HttpRequest, queryset: QuerySet[Loop]) -> None:
        selected = queryset.count()
        paused = 0
        failed: list[Loop] = []
        for loop in queryset.filter(enabled=True, deleted=False):
            try:
                pause_loop(loop, DISABLED_REASON_ADMIN_PAUSED, cancel_runs=False)
                paused += 1
            except Exception:
                # Temporal never lands here: `pause_loop_schedules` swallows and logs its own
                # failures, and a schedule left running can't start anything because `fire_loop`
                # refuses a disabled loop. What reaches this is a failed row save (loop still
                # enabled) or a failed notification dispatch (loop paused, owner not told).
                logger.exception("loop_admin.pause_failed", extra={"loop_id": str(loop.id)})
                failed.append(loop)

        message = f"Paused {paused} of {selected} selected loop(s)."
        if paused + len(failed) < selected:
            message += " Loops that were already paused or deleted were left unchanged."
        self.message_user(request, message)
        if failed:
            failed_ids = ", ".join(str(loop.id) for loop in failed)
            self.message_user(
                request,
                f"Could not pause {len(failed)} loop(s): {failed_ids}. Check the logs and confirm their "
                "state in the list.",
                level=messages.ERROR,
            )

    def delete_model(self, request: HttpRequest, obj: Loop) -> None:
        # Tear down Temporal Schedules before the row is gone; CASCADE never talks to Temporal, so
        # a raw admin delete would otherwise leave the schedules firing forever.
        loop_service.delete_loop_schedules(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset) -> None:
        for loop in queryset:
            loop_service.delete_loop_schedules(loop)
        super().delete_queryset(request, queryset)


@admin.register(LoopTrigger)
class LoopTriggerAdmin(admin.ModelAdmin):
    list_display = ("id", "loop", "type", "enabled", "schedule_sync_status", "last_fired_at")
    list_filter = ("type", "enabled", "schedule_sync_status")
    search_fields = ("loop__name",)
    readonly_fields = ("id", "loop", "enabled", "schedule_sync_status", "last_fired_at", "created_at", "updated_at")
    autocomplete_fields = ("team",)

    def get_queryset(self, request: HttpRequest):
        # Admin has no team context; select_related("loop") also keeps readonly
        # rendering off Loop's fail-closed base manager.
        return LoopTrigger.objects.unscoped().select_related("loop", "team")

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Triggers are created through the loops API; their Temporal Schedule
        # identity hangs off the row id, so hand-created rows would drift.
        return False

    def delete_model(self, request: HttpRequest, obj: LoopTrigger) -> None:
        # Tear down the Temporal Schedule before the row is gone (CASCADE won't).
        loop_service.delete_loop_trigger_schedule(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset) -> None:
        for trigger in queryset:
            loop_service.delete_loop_trigger_schedule(trigger)
        super().delete_queryset(request, queryset)


_AI_RUN_PREFERENCE_KEYS = ("runtime_adapter", "model", "reasoning_effort")


class _TasksConfigAdminForm(forms.ModelForm):
    """Shared form for the two tasks-config admins. Runs the same checks as the API
    write path (`update_team_ai_run_preferences` / `update_user_ai_run_preferences`),
    so an admin edit cannot store a payload the resolver would reject or skip."""

    def clean_team(self):
        team = self.cleaned_data["team"]
        # Preference rows are keyed on the canonical (project root) team; a row keyed on an
        # environment team is never read by the resolver.
        if team is not None and team.parent_team_id is not None:
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
        unknown = sorted(set(prefs) - set(_AI_RUN_PREFERENCE_KEYS))
        if unknown:
            raise forms.ValidationError(
                f"Unknown keys: {', '.join(unknown)}. Allowed: {', '.join(_AI_RUN_PREFERENCE_KEYS)}."
            )
        non_strings = sorted(key for key, value in prefs.items() if not isinstance(value, str))
        if non_strings:
            raise forms.ValidationError(f"Values must be strings: {', '.join(non_strings)}.")
        validate_ai_run_preferences(prefs.get("runtime_adapter"), prefs.get("model"), prefs.get("reasoning_effort"))
        return prefs

    def _post_clean(self) -> None:
        # Unique-constraint validation queries through the model's default manager, which for
        # UserTasksConfig is fail-closed and raises without a team context. Admin requests have
        # none, so scope model validation to the team picked in the form.
        team = self.cleaned_data.get("team")
        if team is None:
            super()._post_clean()
            return
        with team_scope(team.id):
            super()._post_clean()


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
