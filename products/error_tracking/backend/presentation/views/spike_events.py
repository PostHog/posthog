from datetime import datetime
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
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


class _BlankableDateTimeField(serializers.DateTimeField):
    # A blank query param means the caller sent no bound, not a malformed timestamp.
    def to_internal_value(self, value: str) -> datetime | None:  # type: ignore[override]
        if value == "":
            return None
        return super().to_internal_value(value)


class ErrorTrackingSpikeEventListQuerySerializer(serializers.Serializer):
    issue_ids = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Comma-separated issue UUIDs to include.",
    )
    date_from = _BlankableDateTimeField(
        required=False,
        help_text="Include spikes detected at or after this time.",
    )
    date_to = _BlankableDateTimeField(
        required=False,
        help_text="Include spikes detected at or before this time.",
    )
    order_by = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Field to order by. Prefix with a hyphen for descending. An unknown field sorts by newest first.",
    )

    def validate_issue_ids(self, value: str) -> list[str]:
        issue_ids = []
        for candidate in value.split(","):
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                issue_ids.append(str(UUID(candidate)))
            except ValueError:
                raise serializers.ValidationError("Each issue ID must be a UUID.")
        return issue_ids


class ErrorTrackingSpikeEventViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSpikeEventSerializer

    @extend_schema(parameters=[ErrorTrackingSpikeEventListQuerySerializer])
    def list(self, request, *args, **kwargs):
        query = ErrorTrackingSpikeEventListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        date_from = params.get("date_from")
        date_to = params.get("date_to")

        return paginate_via_facade(
            self,
            request,
            lambda limit, offset: error_tracking_api.list_spike_events(
                team_id=self.team.id,
                issue_ids=params.get("issue_ids") or None,
                date_from=date_from.isoformat() if date_from else None,
                date_to=date_to.isoformat() if date_to else None,
                order_by=params.get("order_by") or None,
                limit=limit,
                offset=offset,
            ),
        )
