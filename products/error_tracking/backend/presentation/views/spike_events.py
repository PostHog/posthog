from rest_framework import viewsets
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)
from products.error_tracking.backend.presentation.pagination import paginate_via_facade


class ErrorTrackingSpikeEventSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingSpikeEvent


class ErrorTrackingSpikeEventViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSpikeEventSerializer

    def list(self, request, *args, **kwargs):
        issue_ids_param = request.query_params.get("issue_ids")
        issue_ids = [uid.strip() for uid in issue_ids_param.split(",") if uid.strip()] if issue_ids_param else None
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        order_by = request.query_params.get("order_by")

        return paginate_via_facade(
            self,
            request,
            lambda limit, offset: error_tracking_api.list_spike_events(
                team_id=self.team.id,
                issue_ids=issue_ids or None,
                date_from=date_from,
                date_to=date_to,
                order_by=order_by,
                limit=limit,
                offset=offset,
            ),
        )
