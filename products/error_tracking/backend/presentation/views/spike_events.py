from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)


class ErrorTrackingSpikeEventSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingSpikeEvent


class ErrorTrackingSpikeEventViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSpikeEventSerializer
    pagination_class = FacadeLimitOffsetPagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="issue_ids",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Comma-separated issue UUIDs to include.",
            ),
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Include spikes detected at or after this time.",
            ),
            OpenApiParameter(
                name="date_to",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Include spikes detected at or before this time.",
            ),
            OpenApiParameter(
                name="order_by",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Field to order by. Prefix with a hyphen for descending.",
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        issue_ids_param = request.query_params.get("issue_ids")
        issue_ids = [uid.strip() for uid in issue_ids_param.split(",") if uid.strip()] if issue_ids_param else None
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        order_by = request.query_params.get("order_by")

        return facade_page_response(
            self,
            lambda page: error_tracking_api.list_spike_events(
                team_id=self.team.id,
                issue_ids=issue_ids or None,
                date_from=date_from,
                date_to=date_to,
                order_by=order_by,
                page=page,
            ),
        )
