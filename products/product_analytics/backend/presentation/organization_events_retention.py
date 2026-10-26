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
    choose_organization_events_retention,
    organization_events_retention_choice,
    organization_events_retention_months,
)
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions


class EventsRetentionWindow(models.IntegerChoices):
    ONE_YEAR = 12, "1 year"
    TWO_YEARS = 24, "2 years"
    THREE_YEARS = 36, "3 years"
    FIVE_YEARS = 60, "5 years"
    SEVEN_YEARS = 84, "7 years"


@extend_schema_serializer(many=False)
class OrganizationEventsRetentionSerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="The window an organization admin chose, in months. Null while the organization follows its plan.",
    )
    max_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The longest window the organization's plan allows, in months.",
    )


class OrganizationEventsRetentionUpdateSerializer(serializers.Serializer):
    retention_months = serializers.ChoiceField(
        choices=EventsRetentionWindow.choices,
        help_text="How many months of events every project in the organization keeps queryable. Must not be longer than the organization's plan allows.",
    )


@extend_schema(tags=["events_retention"])
class OrganizationEventsRetentionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "organization"
    pagination_class = None
    permission_classes = [OrganizationAdminWritePermissions]

    def _retention_response(self) -> Response:
        return Response(
            OrganizationEventsRetentionSerializer(
                {
                    "retention_months": organization_events_retention_choice(self.organization),
                    "max_retention_months": organization_events_retention_months(self.organization),
                }
            ).data
        )

    @extend_schema(
        operation_id="organization_events_retention_retrieve",
        summary="Get the organization's events retention window",
        description=(
            "Returns the events retention window an organization admin chose for every project in the "
            "organization, and the longest window the organization's plan allows."
        ),
        responses={200: OrganizationEventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._retention_response()

    @validated_request(
        OrganizationEventsRetentionUpdateSerializer,
        operation_id="organization_events_retention_update",
        summary="Set the organization's events retention window",
        description=(
            "Sets how far back events stay queryable in every project in the organization. The window can't be "
            "longer than the organization's plan allows, and it shortens if the plan later allows less. "
            "Organization admins only."
        ),
        responses={
            200: OpenApiResponse(
                response=OrganizationEventsRetentionSerializer, description="The organization's new window."
            ),
            400: OpenApiResponse(description="The window is not one of the allowed values."),
            403: OpenApiResponse(
                description="The plan doesn't allow this window, or the user isn't an organization admin."
            ),
        },
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        retention_months: int = request.validated_data["retention_months"]
        max_months = organization_events_retention_months(self.organization)
        if retention_months > max_months:
            raise exceptions.PermissionDenied(
                f"This organization's plan allows up to {max_months} months of events retention."
            )

        before_months = organization_events_retention_choice(self.organization)
        choose_organization_events_retention(self.organization, retention_months)
        if retention_months != before_months:
            log_activity(
                organization_id=self.organization.id,
                team_id=None,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                scope="Organization",
                item_id=str(self.organization.id),
                activity="updated",
                detail=Detail(
                    name=str(self.organization.name),
                    changes=[
                        Change(
                            type="Organization",
                            action="changed",
                            field="events_retention_months",
                            before=before_months,
                            after=retention_months,
                        )
                    ],
                ),
            )
        return self._retention_response()
