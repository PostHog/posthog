from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

import structlog

from products.data_warehouse.backend.facade.api import terminate_external_data_workflow, update_external_job_status
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob


def _change_url(job_id) -> str:
    return reverse("admin:warehouse_sources_externaldatajob_change", args=[job_id])


class ExternalDataJobAdminForm(forms.ModelForm):
    # The model has `latest_error = TextField(null=True)` but no `blank=True`, which
    # is the right shape for the DB (Completed jobs legitimately have no error) but
    # Django's ModelForm still treats the form field as required. Mark it optional
    # here so operators can save edits — e.g. clearing a stale error or correcting
    # a stuck job — without inventing placeholder text.
    class Meta:
        model = ExternalDataJob
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "latest_error" in self.fields:
            self.fields["latest_error"].required = False


@admin.register(ExternalDataJob)
class ExternalDataJobAdmin(admin.ModelAdmin):
    form = ExternalDataJobAdminForm
    list_display = (
        "id",
        "status",
        "schema_link",
        "source_type",
        "team_link",
        "rows_synced",
        "billable",
        "created_at",
        "finished_at",
    )
    list_display_links = ("id",)
    list_select_related = ("team", "team__organization", "schema", "pipeline")
    list_filter = ("status", "billable", "pipeline_version")
    search_fields = (
        "id",
        "workflow_id",
        "workflow_run_id",
        "schema__name",
        "team__name",
        "team__organization__name",
    )
    autocomplete_fields = ("team", "schema")
    raw_id_fields = ("pipeline",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "created_by",
        "rows_synced",
        "workflow_id",
        "workflow_run_id",
        "pipeline_version",
        "storage_delta_mib",
        "schema_snapshot",
        "temporal_workflow_link",
        "logs_link",
    )
    ordering = ("-created_at",)

    change_form_template = "admin/data_warehouse/externaldatajob/change_form.html"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "team",
                    "pipeline",
                    "schema",
                    "status",
                    "rows_synced",
                    "billable",
                    "finished_at",
                    "latest_error",
                )
            },
        ),
        (
            "Temporal",
            {
                "fields": (
                    "workflow_id",
                    "workflow_run_id",
                    "temporal_workflow_link",
                    "logs_link",
                )
            },
        ),
        (
            "Pipeline",
            {
                "fields": (
                    "pipeline_version",
                    "storage_delta_mib",
                    "schema_snapshot",
                )
            },
        ),
        (
            "Meta",
            {"fields": ("created_at", "updated_at", "created_by")},
        ),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:job_id>/mark-failed/",
                self.admin_site.admin_view(self.mark_failed_view),
                name="external_data_job_mark_failed",
            ),
        ]
        return custom_urls + urls

    def mark_failed_view(self, request, job_id):
        # Recover an orphaned Running job: the Temporal workflow died (OOM, deploy, SIGKILL) or was
        # terminated without its cleanup activity running, so the job row — and the schema it drives —
        # are stuck on Running forever. This terminates the workflow (forceful, since a dead worker
        # can't process a graceful cancel) and flips both the job and its schema to Failed through the
        # canonical status path, which also stamps finished_at, emits metrics, and fires the failure
        # digest. The pipeline's regular schedule continues independently.
        if request.method != "POST":
            return redirect(_change_url(job_id))

        try:
            job = ExternalDataJob.objects.select_related("schema").get(id=job_id)
        except ExternalDataJob.DoesNotExist:
            messages.error(request, f"Job {job_id} not found.")
            return redirect(reverse("admin:warehouse_sources_externaldatajob_changelist"))

        if not self.has_change_permission(request, job):
            raise PermissionDenied

        if job.status != ExternalDataJob.Status.RUNNING:
            messages.warning(request, f"Job is not Running (status={job.status}). No change.")
            return redirect(_change_url(job_id))

        reason = (request.POST.get("reason") or "").strip()
        latest_error = reason or "Marked Failed via admin (Temporal workflow terminated without cleanup activity)"

        # Best-effort terminate. An already-closed workflow (or a job that never got one) raises —
        # that's fine, we still flip the DB below; just surface what happened to the operator.
        if job.workflow_id:
            try:
                terminate_external_data_workflow(job.workflow_id, reason=latest_error)
                messages.info(request, f"Terminated Temporal workflow {job.workflow_id}.")
            except Exception as e:
                messages.warning(
                    request,
                    f"Could not terminate Temporal workflow {job.workflow_id} ({e}); it may already be "
                    "closed. Continuing to mark the job Failed.",
                )

        if job.schema_id is None:
            # No schema attached — the canonical path can't run (it propagates status to the schema).
            # Fall back to a direct write so a truly orphaned job can still be cleared.
            job.status = ExternalDataJob.Status.FAILED
            job.latest_error = latest_error
            if job.finished_at is None:
                job.finished_at = timezone.now()
            job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])
        else:
            update_external_job_status(
                job_id=str(job.id),
                team_id=job.team_id,
                status=ExternalDataJob.Status.FAILED,
                logger=structlog.get_logger(__name__).bind(team_id=job.team_id),
                latest_error=latest_error,
            )

        messages.success(request, f"Marked job {job.id} (and its schema) as Failed.")
        return redirect(_change_url(job_id))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            extra_context["site_url"] = settings.SITE_URL
            extra_context["temporal_ui_host"] = settings.TEMPORAL_UI_HOST
            extra_context["temporal_namespace"] = settings.TEMPORAL_NAMESPACE
            extra_context["team_id"] = obj.team_id
            extra_context["is_running"] = obj.status == ExternalDataJob.Status.RUNNING
            extra_context["mark_failed_url"] = reverse("admin:external_data_job_mark_failed", args=[obj.id])
            if obj.schema_id:
                extra_context["schema_admin_url"] = reverse(
                    "admin:warehouse_sources_externaldataschema_change", args=[obj.schema_id]
                )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description="Team")
    def team_link(self, job: ExternalDataJob):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[job.team.pk]),
            job.team.name,
        )

    @admin.display(description="Schema")
    def schema_link(self, job: ExternalDataJob):
        if job.schema_id is None:
            return "—"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:warehouse_sources_externaldataschema_change", args=[job.schema_id]),
            job.schema.name if job.schema else job.schema_id,
        )

    @admin.display(description="Source type")
    def source_type(self, job: ExternalDataJob):
        return job.pipeline.source_type

    @admin.display(description="Temporal workflow")
    def temporal_workflow_link(self, job: ExternalDataJob):
        if not job.workflow_id or not job.workflow_run_id:
            return "—"
        url = (
            f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}"
            f"/workflows/{job.workflow_id}/{job.workflow_run_id}"
        )
        return format_html('<a href="{}" target="_blank">View workflow</a>', url)

    @admin.display(description="Logs")
    def logs_link(self, job: ExternalDataJob):
        if not job.workflow_id:
            return "—"
        url = f"{settings.SITE_URL}/project/{job.team_id}/logs?searchTerm={job.workflow_id}"
        return format_html('<a href="{}" target="_blank">View logs</a>', url)
