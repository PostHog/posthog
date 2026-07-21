"""Read-only internal (service-to-service) endpoints API for the modeling-ops admin app.

Lives in the endpoints product (data_modeling cannot depend on endpoints), but shares
the ``api/internal/data_modeling_ops/`` URL prefix and the OIDC auth from the
data_modeling facade. Wired manually in posthog/urls.py.
"""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import extend_schema
from rest_framework import pagination, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.internal_ops import (
    DataModelingOpsAuthenticationMixin,
    scoped_to_team,
    team_id_filter,
)
from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobStatus
from products.endpoints.backend.facade.models import Endpoint, EndpointVersion


class InternalEndpointVersionSerializer(serializers.ModelSerializer):
    is_materialized = serializers.BooleanField(
        read_only=True, help_text="Derived from the saved query's table FK: true when a backing table exists."
    )
    saved_query_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Saved query materializing this version, if any."
    )
    saved_query_status = serializers.SerializerMethodField(help_text="Status of the materializing saved query, if any.")
    saved_query_last_run_at = serializers.SerializerMethodField(
        help_text="saved_query.last_run_at — unreliable on v2 teams (the v2 success path does not write it); "
        "compare with last_successful_job_at."
    )
    saved_query_latest_error = serializers.SerializerMethodField(
        help_text="Latest error of the materializing saved query, untruncated."
    )
    last_successful_job_at = serializers.SerializerMethodField(
        help_text="Completion time of the most recent COMPLETED materialization job for the saved query — "
        "the trustworthy freshness signal."
    )

    class Meta:
        model = EndpointVersion
        fields = [
            "id",
            "version",
            "query",
            "description",
            "is_active",
            "is_materialized",
            "data_freshness_seconds",
            "created_at",
            "last_executed_at",
            "saved_query_id",
            "saved_query_status",
            "saved_query_last_run_at",
            "saved_query_latest_error",
            "last_successful_job_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "query": {"help_text": "Immutable query snapshot for this version."},
            "data_freshness_seconds": {"help_text": "Freshness target controlling cache TTL and sync cadence."},
        }

    def get_saved_query_status(self, version: EndpointVersion) -> str | None:
        return version.saved_query.status if version.saved_query else None

    def get_saved_query_last_run_at(self, version: EndpointVersion) -> str | None:
        if version.saved_query and version.saved_query.last_run_at:
            return version.saved_query.last_run_at.isoformat()
        return None

    def get_saved_query_latest_error(self, version: EndpointVersion) -> str | None:
        return version.saved_query.latest_error if version.saved_query else None

    def get_last_successful_job_at(self, version: EndpointVersion) -> str | None:
        last_successful_job_at = self.context.get("last_successful_job_at_by_saved_query", {}).get(
            version.saved_query_id
        )
        return last_successful_job_at.isoformat() if last_successful_job_at else None


class InternalEndpointSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Endpoint
        fields = [
            "id",
            "name",
            "is_active",
            "current_version",
            "derived_from_insight",
            "created_at",
            "last_executed_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "name": {"help_text": "Endpoint name, unique per team and used in its run path."},
            "is_active": {"help_text": "False when the endpoint is disabled and rejects runs."},
            "current_version": {"help_text": "Version number served by the run path."},
            "derived_from_insight": {"help_text": "Insight this endpoint was created from, if any."},
            "last_executed_at": {"help_text": "Last time any version of this endpoint was run."},
        }


class InternalEndpointsOpsPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 500


class InternalEndpointsOpsViewSet(DataModelingOpsAuthenticationMixin, TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Internal read-only endpoint data for the modeling-ops admin app."""

    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    pagination_class = InternalEndpointsOpsPagination

    @extend_schema(exclude=True)
    def internal_endpoints(self, request: Request, **kwargs: Any) -> Response:
        queryset = scoped_to_team(Endpoint.objects.exclude(deleted=True), team_id_filter(request)).order_by(
            "team_id", "name"
        )
        page = self.paginate_queryset(queryset)
        serializer = InternalEndpointSummarySerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(exclude=True)
    def internal_endpoint_detail(self, request: Request, endpoint_id: str, **kwargs: Any) -> Response:
        # Looked up by id rather than name: names are unique per team, ids are unique
        # everywhere, so the caller does not have to know the team to fetch one.
        try:
            endpoint = Endpoint.objects.filter(id=endpoint_id).exclude(deleted=True).first()
        except (DjangoValidationError, ValueError):
            return Response({"error": "Endpoint not found"}, status=404)
        if endpoint is None:
            return Response({"error": "Endpoint not found"}, status=404)

        team_id = endpoint.team_id
        versions = list(endpoint.versions.select_related("saved_query").all())
        saved_query_ids = [v.saved_query_id for v in versions if v.saved_query_id]
        last_successful_job_at_by_saved_query = {}
        if saved_query_ids:
            successful_jobs = (
                DataModelingJob.objects.filter(
                    team_id=int(team_id),
                    saved_query_id__in=saved_query_ids,
                    status=DataModelingJobStatus.COMPLETED,
                )
                .order_by("saved_query_id", "-updated_at")
                .distinct("saved_query_id")
                .values_list("saved_query_id", "updated_at")
            )
            last_successful_job_at_by_saved_query = dict(successful_jobs)

        return Response(
            {
                **InternalEndpointSummarySerializer(endpoint).data,
                "versions": InternalEndpointVersionSerializer(
                    versions,
                    many=True,
                    context={"last_successful_job_at_by_saved_query": last_successful_job_at_by_saved_query},
                ).data,
            }
        )
