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

# Kept in sync with `logic.SPIKE_EVENT_ORDER_FIELDS`; duplicated here to respect the product's
# facade boundary (the presentation layer must not import from `logic`). An unlisted value is
# ignored by the facade, so drift only widens what the API rejects, never causes a 500.
SPIKE_EVENT_ORDER_FIELDS = (
    "detected_at",
    "-detected_at",
    "computed_baseline",
    "-computed_baseline",
    "current_bucket_value",
    "-current_bucket_value",
)


class ErrorTrackingSpikeEventSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingSpikeEvent


class SpikeEventsListQuerySerializer(serializers.Serializer):
    issue_ids = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Comma-separated list of issue UUIDs to filter spike events by. Omit for all issues.",
    )
    date_from = serializers.DateTimeField(
        required=False,
        help_text="Only return spike events detected at or after this ISO 8601 timestamp.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text="Only return spike events detected at or before this ISO 8601 timestamp.",
    )
    order_by = serializers.ChoiceField(
        choices=SPIKE_EVENT_ORDER_FIELDS,
        required=False,
        help_text="Field to order results by. Defaults to newest first (-detected_at).",
    )

    def validate_issue_ids(self, value: str) -> list[str]:
        ids = [uid.strip() for uid in value.split(",") if uid.strip()]
        for uid in ids:
            try:
                UUID(uid)
            except ValueError:
                raise serializers.ValidationError(f"'{uid}' is not a valid issue id.")
        return ids


class ErrorTrackingSpikeEventViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSpikeEventSerializer

    @extend_schema(
        parameters=[SpikeEventsListQuerySerializer],
        responses={200: ErrorTrackingSpikeEventSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        query = SpikeEventsListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        issue_ids = params.get("issue_ids") or None
        date_from = params.get("date_from")
        date_to = params.get("date_to")

        return paginate_via_facade(
            self,
            request,
            lambda limit, offset: error_tracking_api.list_spike_events(
                team_id=self.team.id,
                issue_ids=issue_ids,
                date_from=date_from.isoformat() if date_from else None,
                date_to=date_to.isoformat() if date_to else None,
                order_by=params.get("order_by"),
                limit=limit,
                offset=offset,
            ),
        )
