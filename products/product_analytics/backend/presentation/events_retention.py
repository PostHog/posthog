from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.event_retention import events_retention_floor_date, events_retention_months_for_team

EVENTS_RETENTION_DOCS_URL = "https://posthog.com/docs/data/events-retention"


@extend_schema_serializer(many=False)
class EventsRetentionSerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="How many months of events stay queryable, counted back from today. Null while no retention window applies to the project.",
    )
    retained_from = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="The earliest date whose events are still queryable, in the project's timezone. Null while no retention window applies to the project.",
    )
    docs_url = serializers.URLField(
        read_only=True,
        help_text="Where the events retention policy is documented.",
    )


@extend_schema(tags=["events_retention"])
class EventsRetentionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "project"
    pagination_class = None

    @extend_schema(
        operation_id="events_retention_retrieve",
        summary="Get the events retention window for a project",
        description=(
            "Returns how far back events stay queryable for this project. The window comes from the "
            "organization's plan and is read-only. Both window fields are null while no retention window "
            "applies to the project."
        ),
        responses={200: EventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        retention_months = events_retention_months_for_team(self.team, self.team_id)
        retained_from = (
            events_retention_floor_date(self.team, retention_months) if retention_months is not None else None
        )
        return Response(
            EventsRetentionSerializer(
                {
                    "retention_months": retention_months,
                    "retained_from": retained_from,
                    "docs_url": EVENTS_RETENTION_DOCS_URL,
                }
            ).data
        )
