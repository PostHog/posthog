from __future__ import annotations

import re
from functools import partial
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import admin, messages
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpRequest

from posthog.models import Organization, User

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
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
    selected_saved_query_ids = forms.CharField(
        required=False,
        label="Selected view IDs",
        help_text="Enter one saved-query UUID per line. This field is required when the scope is Selected views.",
        widget=forms.Textarea(attrs={"rows": 8}),
    )

    class Meta:
        model = ManagedWarehouseViewTranslationJob
        fields = ("organization", "scope", "selected_saved_query_ids")

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

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        if cleaned_data is None:
            return {}

        raw_ids = cleaned_data.get("selected_saved_query_ids")
        tokens = re.split(r"[\s,]+", raw_ids.strip()) if isinstance(raw_ids, str) and raw_ids.strip() else []
        try:
            selected_ids = list(dict.fromkeys(str(UUID(token)) for token in tokens))
        except ValueError:
            self.add_error(
                "selected_saved_query_ids",
                "Enter valid saved-query UUIDs separated by commas or new lines.",
            )
            selected_ids = []
        cleaned_data["selected_saved_query_ids"] = selected_ids

        scope = cleaned_data.get("scope")
        if scope == ManagedWarehouseViewTranslationJob.Scope.ENTIRE_ORGANIZATION and selected_ids:
            self.add_error(
                "selected_saved_query_ids",
                "Leave this field empty when the scope is Entire organization.",
            )
        if scope == ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS and not selected_ids:
            self.add_error(
                "selected_saved_query_ids",
                "Enter at least one saved-query UUID when the scope is Selected views.",
            )

        organization = cleaned_data.get("organization")
        if isinstance(organization, Organization) and selected_ids:
            eligible_ids = {
                str(saved_query_id)
                for saved_query_id in DataWarehouseSavedQuery.objects.filter(
                    id__in=selected_ids,
                    team__organization_id=organization.id,
                    deleted=False,
                )
                .exclude(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)
                .values_list("id", flat=True)
            }
            if eligible_ids != set(selected_ids):
                self.add_error(
                    "selected_saved_query_ids",
                    "One or more IDs do not identify an active view in this organization. Check the IDs and try again.",
                )

        return cleaned_data


@admin.register(ManagedWarehouseViewTranslationJob)
class ManagedWarehouseViewTranslationJobAdmin(admin.ModelAdmin):
    form = ManagedWarehouseViewTranslationJobForm
    list_display = (
        "id",
        "organization_id",
        "status",
        "trigger_source",
        "scope",
        "total_count",
        "compiled_count",
        "failed_count",
        "stale_count",
        "created_at",
        "finished_at",
    )
    list_filter = ("status", "trigger_source", "scope")
    search_fields = ("=id", "=organization__id", "=retry_of__id", "workflow_id", "workflow_run_id")
    raw_id_fields = ("organization", "created_by", "retry_of")
    ordering = ("-created_at",)

    def get_fields(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationJob | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return ("organization", "scope", "selected_saved_query_ids")
        return (
            "id",
            "organization",
            "created_by",
            "trigger_source",
            "scope",
            "selected_saved_query_ids",
            "retry_of",
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
    actions = ("retry_selected_translations",)
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

    @admin.action(description="Retry selected translations")
    def retry_selected_translations(
        self,
        request: HttpRequest,
        queryset: QuerySet[ManagedWarehouseViewTranslationResult],
    ) -> None:
        results = list(queryset.select_related("job").order_by("saved_query_id"))
        source_job_ids = {result.job_id for result in results}
        if len(source_job_ids) != 1:
            self.message_user(request, "Select results from one translation job.", level=messages.ERROR)
            return
        if any(
            result.status
            not in [
                ManagedWarehouseViewTranslationResult.Status.FAILED,
                ManagedWarehouseViewTranslationResult.Status.STALE,
            ]
            for result in results
        ):
            self.message_user(request, "Select only failed or stale translation results.", level=messages.ERROR)
            return

        source_job = results[0].job
        if ManagedWarehouseViewTranslationJob.objects.filter(
            organization_id=source_job.organization_id,
            status__in=[
                ManagedWarehouseViewTranslationJob.Status.PENDING,
                ManagedWarehouseViewTranslationJob.Status.RUNNING,
            ],
        ).exists():
            self.message_user(
                request,
                "This organization already has a pending or running translation job. Wait for it to finish before retrying.",
                level=messages.ERROR,
            )
            return

        selected_ids = list(dict.fromkeys(str(result.saved_query_id) for result in results))
        try:
            with transaction.atomic():
                retry_job = ManagedWarehouseViewTranslationJob.objects.create(
                    organization_id=source_job.organization_id,
                    created_by=cast(User, request.user),
                    trigger_source=ManagedWarehouseViewTranslationJob.TriggerSource.RETRY,
                    scope=ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS,
                    selected_saved_query_ids=selected_ids,
                    retry_of=source_job,
                )
                transaction.on_commit(partial(_start_translation_job, retry_job.id, retry_job.organization_id))
        except IntegrityError:
            self.message_user(
                request,
                "This organization already has a pending or running translation job. Wait for it to finish before retrying.",
                level=messages.ERROR,
            )
            return

        self.message_user(
            request,
            f"Created retry job {retry_job.id}. Selected views: {len(selected_ids)}.",
            level=messages.SUCCESS,
        )

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
