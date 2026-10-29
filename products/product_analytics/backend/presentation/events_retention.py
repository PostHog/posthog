from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team.event_retention import events_retention_floor_date, events_retention_months_for_team
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions

from products.product_analytics.backend.facade.events_retention import (
    organization_events_retention,
    project_events_retention_months,
    set_organization_events_retention,
    set_project_events_retention,
)

EVENTS_RETENTION_DOCS_URL = "https://posthog.com/docs/data/events-retention"


@extend_schema_serializer(many=False)
class OrganizationEventsRetentionSerializer(serializers.Serializer):
    organization_retention_months = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="The window, in months, that every project without its own window uses. Null while the organization keeps events for its plan's window.",
    )
    plan_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The longest window the organization's plan allows, in months.",
    )
    min_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The shortest window an admin can set, in months.",
    )
    max_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The longest window an admin can set, in months. Never longer than the plan's window.",
    )


@extend_schema_serializer(many=False)
class EventsRetentionSerializer(OrganizationEventsRetentionSerializer):
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
    project_retention_months = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="The window, in months, set for this project. Null while the project uses the organization's window.",
    )


class EventsRetentionUpdateSerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        allow_null=True,
        min_value=1,
        help_text="The window in months. Events older than this are deleted on the next monthly cleanup and can't be restored. Null removes the window.",
    )


@extend_schema(tags=["events_retention"])
class EventsRetentionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "project"
    pagination_class = None
    permission_classes = [OrganizationAdminWritePermissions]

    def _retention_response(self) -> Response:
        retention_months = events_retention_months_for_team(self.team, self.team_id)
        retained_from = (
            events_retention_floor_date(self.team, retention_months) if retention_months is not None else None
        )
        organization = organization_events_retention(self.organization)
        return Response(
            EventsRetentionSerializer(
                {
                    "retention_months": retention_months,
                    "retained_from": retained_from,
                    "docs_url": EVENTS_RETENTION_DOCS_URL,
                    "project_retention_months": project_events_retention_months(self.team),
                    "organization_retention_months": organization.organization_months,
                    "plan_retention_months": organization.plan_months,
                    "min_retention_months": organization.min_months,
                    "max_retention_months": organization.max_months,
                }
            ).data
        )

    @extend_schema(
        operation_id="events_retention_retrieve",
        summary="Get the events retention window for a project",
        description=(
            "Returns how far back events stay queryable for this project, the windows set for the project and its "
            "organization, and the range an admin can set. Both window fields are null while no retention window "
            "applies to the project."
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
            "Sets how long this project keeps events, overriding the organization's window. Events older than the "
            "window are deleted on the next monthly cleanup and can't be restored. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsRetentionSerializer, description="The project's new window."),
            400: OpenApiResponse(description="The window is outside the range an admin can set."),
            403: OpenApiResponse(description="The user isn't an organization admin."),
        },
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        try:
            set_project_events_retention(
                self.team,
                request.validated_data["retention_months"],
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages) from error
        return self._retention_response()


@extend_schema(tags=["events_retention"])
class OrganizationEventsRetentionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "organization"
    pagination_class = None
    permission_classes = [OrganizationAdminWritePermissions]

    def _retention_response(self) -> Response:
        organization = organization_events_retention(self.organization)
        return Response(
            OrganizationEventsRetentionSerializer(
                {
                    "organization_retention_months": organization.organization_months,
                    "plan_retention_months": organization.plan_months,
                    "min_retention_months": organization.min_months,
                    "max_retention_months": organization.max_months,
                }
            ).data
        )

    @extend_schema(
        operation_id="organization_events_retention_retrieve",
        summary="Get the organization's events retention window",
        description=(
            "Returns the events retention window that every project without its own window uses, and the range an "
            "organization admin can set."
        ),
        responses={200: OrganizationEventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._retention_response()

    @validated_request(
        EventsRetentionUpdateSerializer,
        operation_id="organization_events_retention_update",
        summary="Set the organization's events retention window",
        description=(
            "Sets how long every project without its own window keeps events. Events older than the window are "
            "deleted on the next monthly cleanup and can't be restored. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(
                response=OrganizationEventsRetentionSerializer, description="The organization's new window."
            ),
            400: OpenApiResponse(description="The window is outside the range an admin can set."),
            403: OpenApiResponse(description="The user isn't an organization admin."),
        },
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        try:
            set_organization_events_retention(
                self.organization,
                request.validated_data["retention_months"],
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages) from error
        return self._retention_response()
