from uuid import UUID

from django.db import models

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)
from products.error_tracking.backend.presentation.pagination import paginate_via_facade


# This enum mirrors logic.SPIKE_EVENT_ORDER_FIELDS because the presentation layer must not import logic.
class SpikeEventOrderBy(models.TextChoices):
    DETECTED_AT = "detected_at", "detected_at"
    DETECTED_AT_DESC = "-detected_at", "-detected_at"
    COMPUTED_BASELINE = "computed_baseline", "computed_baseline"
    COMPUTED_BASELINE_DESC = "-computed_baseline", "-computed_baseline"
    CURRENT_BUCKET_VALUE = "current_bucket_value", "current_bucket_value"
    CURRENT_BUCKET_VALUE_DESC = "-current_bucket_value", "-current_bucket_value"


@extend_schema_field(
    {
        "type": "string",
        "enum": SpikeEventOrderBy.values,
        "x-enum-varnames": SpikeEventOrderBy.names,
    }
)
class SpikeEventOrderByField(serializers.ChoiceField):
    pass


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
    order_by = SpikeEventOrderByField(
        choices=SpikeEventOrderBy.choices,
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
