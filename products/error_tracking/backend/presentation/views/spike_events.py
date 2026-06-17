from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

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

    def list(self, request, *args, **kwargs):
        issue_ids_param = request.query_params.get("issue_ids")
        issue_ids = [uid.strip() for uid in issue_ids_param.split(",") if uid.strip()] if issue_ids_param else None

        events = error_tracking_api.list_spike_events(
            team_id=self.team.id,
            issue_ids=issue_ids or None,
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
            order_by=request.query_params.get("order_by"),
        )

        page = self.paginate_queryset(events)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(events, many=True).data)
