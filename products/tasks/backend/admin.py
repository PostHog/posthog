from django.contrib import admin, messages
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.storage import object_storage

from .models import CodeInvite, CodeInviteRedemption, SandboxSnapshot, Task, TaskRun


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


class CodeInviteRedemptionInline(admin.TabularInline):
    model = CodeInviteRedemption
    extra = 0
    can_delete = False
    readonly_fields = ("id", "user", "organization", "redeemed_at")


@admin.register(CodeInvite)
class CodeInviteAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "description",
        "is_active",
        "redemption_count",
        "max_redemptions",
        "expires_at",
        "created_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("code", "description")
    readonly_fields = ("id", "redemption_count", "created_at")
    autocomplete_fields = ("created_by",)
    inlines = []

    def get_fieldsets(self, request, obj=None):
        if obj:
            return (
                (None, {"fields": ("id", "code", "description")}),
                ("Limits", {"fields": ("is_active", "max_redemptions", "redemption_count", "expires_at")}),
                ("Metadata", {"fields": ("created_by", "created_at")}),
            )
        # On add, code may be set manually or left blank to auto-generate on save
        return (
            (None, {"fields": ("id", "code", "description")}),
            ("Limits", {"fields": ("is_active", "max_redemptions", "expires_at")}),
            ("Metadata", {"fields": ("created_by",)}),
        )

    def get_inlines(self, request, obj=None):
        return [CodeInviteRedemptionInline]


@admin.register(CodeInviteRedemption)
class CodeInviteRedemptionAdmin(admin.ModelAdmin):
    list_display = ("invite_code", "user", "organization", "redeemed_at")
    list_filter = ("redeemed_at",)
    search_fields = ("user__email", "invite_code__code")
    readonly_fields = ("id", "invite_code", "user", "organization", "redeemed_at")
