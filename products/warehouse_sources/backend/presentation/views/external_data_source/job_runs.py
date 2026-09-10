"""Serializers and endpoints for external data jobs."""

from __future__ import annotations

from typing import Any

from django.utils.cache import patch_cache_control

from dateutil import parser
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action

from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSource
from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    SimpleExternalDataSchemaSerializer,
)
from products.warehouse_sources.backend.presentation.views.public_source_configs import build_source_configs

from . import base


class ExternalDataJobSerializers(serializers.ModelSerializer):
    schema = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    cdc_write_mode = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "For CDC syncs with `cdc_table_mode='both'`, distinguishes the two ExternalDataJob "
            "rows produced per sync: `incremental_merge` (consolidated table) vs `scd2_append` "
            "(cdc-only history table). `null` for non-CDC syncs. Read from `schema_snapshot`."
        ),
    )
    billable = serializers.BooleanField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Whether the rows synced by this job count toward billing. `false` for system-initiated "
            "runs the customer isn't charged for (e.g. rebuilding a table after an internal issue). "
            "`null` on legacy rows and means billable."
        ),
    )
    destination_ids = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Destinations this run delivered to, snapshotted when it started. Empty on runs that "
            "predate destinations, which wrote to the PostHog warehouse alone. `rows_synced` counts "
            "the rows read from the source once, not once per destination."
        ),
    )

    class Meta:
        model = ExternalDataJob
        fields = [
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "status",
            "schema",
            "rows_synced",
            "latest_error",
            "workflow_run_id",
            "cdc_write_mode",
            "billable",
            "destination_ids",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "status",
            "schema",
            "rows_synced",
            "latest_error",
            "workflow_run_id",
            "cdc_write_mode",
            "billable",
            "destination_ids",
        ]

    def get_cdc_write_mode(self, instance: ExternalDataJob) -> str | None:
        return (instance.schema_snapshot or {}).get("cdc_write_mode")

    def get_status(self, instance: ExternalDataJob):
        if instance.status == ExternalDataJob.Status.BILLING_LIMIT_REACHED:
            return "Billing limits"

        if instance.status == ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW:
            return "Billing limit too low"

        return instance.status

    def get_schema(self, instance: ExternalDataJob):
        return SimpleExternalDataSchemaSerializer(
            instance.schema, many=False, read_only=True, context=self.context
        ).data


class ExternalDataSourceJobRunsMixin(base.ExternalDataSourceViewSetBase):
    @action(methods=["GET"], detail=True, pagination_class=None)
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="after",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO timestamp — only return jobs created after this date.",
            ),
            OpenApiParameter(
                name="before",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO timestamp — only return jobs created before this date.",
            ),
            OpenApiParameter(
                name="schemas",
                type={"type": "array", "items": {"type": "string"}},
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter jobs by table schema names.",
            ),
        ],
        responses=ExternalDataJobSerializers(many=True),
    )
    def jobs(self, request: Request, *arg: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()
        after = request.query_params.get("after", None)
        before = request.query_params.get("before", None)
        schemas = request.query_params.getlist("schemas")

        # select_related joins the full ExternalDataSchema row; defer its large JSON/text
        # columns so the serializer only pulls the fields SimpleExternalDataSchemaSerializer
        # actually reads (sync_type_config + latest_error can each be sizeable).
        # Non-billable jobs are included on purpose: the UI shows them tagged so a sync the
        # customer wasn't charged for is still visible in the history.
        jobs = (
            instance.jobs.select_related("schema")
            .defer("schema__sync_type_config", "schema__latest_error")
            .order_by("-created_at")
        )

        if schemas:
            jobs = jobs.filter(schema__name__in=schemas)
        if after:
            after_date = parser.parse(after)
            jobs = jobs.filter(created_at__gt=after_date)
        if before:
            before_date = parser.parse(before)
            jobs = jobs.filter(created_at__lt=before_date)

        jobs = jobs[:50]

        return Response(
            status=status.HTTP_200_OK,
            data=ExternalDataJobSerializers(
                jobs, many=True, read_only=True, context=self.get_serializer_context()
            ).data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Comma-separated source type(s) to return config for, e.g. 'Postgres' or "
                    "'Postgres,Stripe'. Strongly recommended: the unfiltered response describes every "
                    "supported source and is very large. Omit only to enumerate the available types."
                ),
            )
        ],
    )
    @action(methods=["GET"], detail=False)
    def wizard(self, request: Request, *arg: Any, **kwargs: Any):
        # The documented-tables catalog is only consumed by the posthog.com docs build (via the
        # public endpoint) — skipping it here cuts ~40% off an already >1 MB response.
        configs = build_source_configs(include_tables=False)

        requested = request.query_params.get("source_type")
        if requested:
            requested_types = [t.strip() for t in requested.split(",") if t.strip()]
            unknown = [t for t in requested_types if t not in configs]
            if unknown:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": f"Unknown source_type(s): {', '.join(sorted(unknown))}. "
                        "Omit source_type to list every available type."
                    },
                )
            configs = {st: config for st, config in configs.items() if st in requested_types}

        response = Response(status=status.HTTP_200_OK, data=configs)
        # The catalog is deploy-static and identical for every user (no team/user input), so let the
        # browser reuse it across navigations instead of re-downloading and re-parsing several hundred
        # KB on each visit to the new-source page. `private` because the route is auth-gated; a new
        # source ships at most once per deploy, so a short freshness window is safe.
        patch_cache_control(response, private=True, max_age=600)
        return response
