from __future__ import annotations

from functools import partial
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import admin
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest

from posthog.models import Organization, User

from products.managed_warehouse.backend.models import (
    DuckgresServer,
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)


def _start_translation_job(job_id: UUID, organization_id: UUID) -> None:
    from products.managed_warehouse.backend.view_translation import (  # noqa: PLC0415 - keeps the Temporal client off Django startup paths
        start_managed_warehouse_view_translation,
    )

    start_managed_warehouse_view_translation(job_id, organization_id)


class ManagedWarehouseViewTranslationJobForm(forms.ModelForm):
    class Meta:
        model = ManagedWarehouseViewTranslationJob
        fields = ("organization",)

    def clean_organization(self) -> Organization:
        organization = cast(Organization, self.cleaned_data["organization"])
        if not DuckgresServer.objects.filter(organization=organization).exists():
            raise forms.ValidationError("This organization does not have a provisioned managed warehouse.")
        if ManagedWarehouseViewTranslationJob.objects.filter(
            organization=organization,
            status__in=[
                ManagedWarehouseViewTranslationJob.Status.PENDING,
                ManagedWarehouseViewTranslationJob.Status.RUNNING,
            ],
        ).exists():
            raise forms.ValidationError("This organization already has a pending or running translation job.")
        return organization


@admin.register(ManagedWarehouseViewTranslationJob)
class ManagedWarehouseViewTranslationJobAdmin(admin.ModelAdmin):
    form = ManagedWarehouseViewTranslationJobForm
    list_display = (
        "id",
        "organization_id",
        "status",
        "trigger_source",
        "total_count",
        "compiled_count",
        "failed_count",
        "stale_count",
        "created_at",
        "finished_at",
    )
    list_filter = ("status", "trigger_source")
    search_fields = ("=id", "=organization__id", "workflow_id", "workflow_run_id")
    raw_id_fields = ("organization", "created_by")
    ordering = ("-created_at",)

    def get_fields(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationJob | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return ("organization",)
        return (
            "id",
            "organization",
            "created_by",
            "trigger_source",
            "status",
            "workflow_id",
            "workflow_run_id",
            "started_at",
            "finished_at",
            "total_count",
            "compiled_count",
            "failed_count",
            "stale_count",
            "latest_error",
            "created_at",
            "updated_at",
        )

    def get_readonly_fields(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationJob | None = None
    ) -> tuple[str, ...]:
        return () if obj is None else self.get_fields(request, obj)

    def save_model(
        self,
        request: HttpRequest,
        obj: ManagedWarehouseViewTranslationJob,
        form: forms.ModelForm,
        change: bool,
    ) -> None:
        if not change:
            obj.created_by = cast(User, request.user)
            obj.trigger_source = ManagedWarehouseViewTranslationJob.TriggerSource.ADMIN
            obj.status = ManagedWarehouseViewTranslationJob.Status.PENDING
        super().save_model(request, obj, form, change)
        if not change:
            transaction.on_commit(partial(_start_translation_job, obj.id, obj.organization_id))

    def has_delete_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationJob | None = None
    ) -> bool:
        return False


@admin.register(ManagedWarehouseViewTranslationResult)
class ManagedWarehouseViewTranslationResultAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "job_id",
        "team_id",
        "saved_query_name",
        "is_materialized",
        "status",
        "processed_at",
    )
    list_filter = ("status", "is_materialized")
    search_fields = ("=id", "=job__id", "=team__id", "=saved_query_id", "saved_query_name")
    raw_id_fields = ("job", "team")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "job",
        "team",
        "saved_query_id",
        "saved_query_name",
        "is_materialized",
        "source_query_hash",
        "status",
        "trino_sql",
        "trino_values",
        "normalized_hogql",
        "error_type",
        "error_message",
        "processed_at",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[ManagedWarehouseViewTranslationResult]:
        return ManagedWarehouseViewTranslationResult.all_teams.select_related("job", "team")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationResult | None = None
    ) -> bool:
        return False

    def has_view_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationResult | None = None
    ) -> bool:
        return True

    def has_delete_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationResult | None = None
    ) -> bool:
        return False
