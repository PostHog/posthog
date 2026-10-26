from typing import Any, cast

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.team.event_retention import (
    choose_team_events_retention,
    events_retention_floor_date,
    events_retention_months_for_team,
    organization_events_retention_months,
)
from posthog.models.user import User
from posthog.models.utils import UUIDT
from posthog.permissions import TeamMemberStrictManagementPermission

EVENTS_RETENTION_DOCS_URL = "https://posthog.com/docs/data/events-retention"


class EventsRetentionWindow(models.IntegerChoices):
    ONE_YEAR = 12, "1 year"
    TWO_YEARS = 24, "2 years"
    THREE_YEARS = 36, "3 years"
    FIVE_YEARS = 60, "5 years"
    SEVEN_YEARS = 84, "7 years"


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
    max_retention_months = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="The longest window the organization's plan allows, in months. Null while no retention window applies to the project.",
    )
    docs_url = serializers.URLField(
        read_only=True,
        help_text="Where the events retention policy is documented.",
    )


class EventsRetentionUpdateSerializer(serializers.Serializer):
    retention_months = serializers.ChoiceField(
        choices=EventsRetentionWindow.choices,
        help_text="How many months of events to keep queryable. Must not be longer than the organization's plan allows.",
    )


@extend_schema(tags=["events_retention"])
class EventsRetentionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "project"
    pagination_class = None
    permission_classes = [TeamMemberStrictManagementPermission]

    def _retention_response(self) -> Response:
        retention_months = events_retention_months_for_team(self.team, self.team_id)
        window: dict[str, Any] = {"retention_months": None, "retained_from": None, "max_retention_months": None}
        if retention_months is not None:
            window = {
                "retention_months": retention_months,
                "retained_from": events_retention_floor_date(self.team, retention_months),
                "max_retention_months": organization_events_retention_months(self.organization),
            }
        return Response(EventsRetentionSerializer({**window, "docs_url": EVENTS_RETENTION_DOCS_URL}).data)

    @extend_schema(
        operation_id="events_retention_retrieve",
        summary="Get the events retention window for a project",
        description=(
            "Returns how far back events stay queryable for this project, and the longest window the "
            "organization's plan allows. All window fields are null while no retention window applies to "
            "the project."
        ),
        responses={200: EventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._retention_response()

    @validated_request(
        EventsRetentionUpdateSerializer,
        operation_id="events_retention_update",
        summary="Set the events retention window for a project",
        description=(
            "Sets how far back events stay queryable for this project. The window can't be longer than the "
            "organization's plan allows, and it shortens if the plan later allows less. Project admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsRetentionSerializer, description="The project's new window."),
            400: OpenApiResponse(description="The window is not one of the allowed values."),
            403: OpenApiResponse(description="The plan doesn't allow this window, or the user isn't a project admin."),
        },
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        retention_months: int = request.validated_data["retention_months"]
        max_months = organization_events_retention_months(self.organization)
        if retention_months > max_months:
            raise exceptions.PermissionDenied(
                f"This organization's plan allows up to {max_months} months of events retention."
            )

        before_months = self.team.event_retention_months
        after_months = choose_team_events_retention(self.team, retention_months)
        if after_months != before_months:
            log_activity(
                organization_id=cast(UUIDT, self.organization.id),
                team_id=self.team.pk,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                scope="Team",
                item_id=self.team.pk,
                activity="updated",
                detail=Detail(
                    name=str(self.team.name),
                    changes=[
                        Change(
                            type="Team",
                            action="changed",
                            field="events_retention_months",
                            before=before_months,
                            after=after_months,
                        )
                    ],
                ),
            )
        return self._retention_response()
