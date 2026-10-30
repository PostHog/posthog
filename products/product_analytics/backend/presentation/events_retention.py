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

from products.product_analytics.backend.facade.contracts import OrganizationEventsRetention
from products.product_analytics.backend.facade.events_retention import (
    organization_events_retention,
    project_events_retention,
    set_organization_events_retention,
    set_project_events_retention,
)

EVENTS_RETENTION_DOCS_URL = "https://posthog.com/docs/data/events-retention"


@extend_schema_serializer(many=False)
class OrganizationEventsRetentionSerializer(serializers.Serializer):
    organization_retention_months = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="The window, in months, that every project without its own window uses. Null while the organization uses the default window.",
    )
    organization_delete_monthly = serializers.BooleanField(
        read_only=True,
        help_text="Whether projects that use the organization's window delete events older than it at every monthly cleanup. When false, they're deleted at the cleanup every 3 months.",
    )
    plan_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The longest window the organization's plan allows, in months.",
    )
    default_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The window, in months, that a project uses when neither it nor the organization sets one: 24 months, or the plan's window if that's shorter.",
    )
    min_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The shortest window an admin can set, in months.",
    )
    max_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The longest window an admin can set, in months. Never longer than the plan's window.",
    )
    next_monthly_cleanup_on = serializers.DateField(
        read_only=True,
        help_text="The date of the next monthly cleanup, in the timezone it runs in.",
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
    delete_monthly = serializers.BooleanField(
        read_only=True,
        help_text="Whether the project's window deletes older events at every monthly cleanup. When false, they're deleted at the cleanup every 3 months, at least 3 months after the window gets shorter.",
    )
    next_deletion_on = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="The date of the next cleanup that deletes this project's events. Null while no deletion is scheduled.",
    )
    next_deletion_before = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="The next cleanup deletes this project's events from before this date. Null while no deletion is scheduled.",
    )


class EventsRetentionUpdateSerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        allow_null=True,
        min_value=1,
        help_text="The window in months. Older events are deleted and can't be restored. Null removes the window.",
    )
    delete_monthly = serializers.BooleanField(
        default=False,
        help_text="Delete events older than the window at every monthly cleanup. When false, they're deleted at the cleanup every 3 months, at least 3 months after the window gets shorter. Needs a window.",
    )


def _organization_fields(organization: OrganizationEventsRetention) -> dict[str, Any]:
    return {
        "organization_retention_months": organization.organization_months,
        "organization_delete_monthly": organization.organization_delete_monthly,
        "plan_retention_months": organization.plan_months,
        "default_retention_months": organization.default_months,
        "min_retention_months": organization.min_months,
        "max_retention_months": organization.max_months,
        "next_monthly_cleanup_on": organization.next_cleanup_on,
    }


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
        project = project_events_retention(self.team)
        return Response(
            EventsRetentionSerializer(
                {
                    "retention_months": retention_months,
                    "retained_from": retained_from,
                    "docs_url": EVENTS_RETENTION_DOCS_URL,
                    "project_retention_months": project.project_months,
                    "delete_monthly": project.delete_monthly,
                    "next_deletion_on": project.next_deletion.deletes_on if project.next_deletion else None,
                    "next_deletion_before": project.next_deletion.deletes_before if project.next_deletion else None,
                    **_organization_fields(organization_events_retention(self.organization)),
                }
            ).data
        )

    @extend_schema(
        operation_id="events_retention_retrieve",
        summary="Get the events retention window for a project",
        description=(
            "Returns how far back events stay queryable for this project, the windows set for the project and its "
            "organization, the range an admin can set, and the project's next deletion. Both queryable window fields "
            "are null while no retention window applies to the project."
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
            "Sets how long this project keeps events, overriding the organization's window, and whether older events "
            "are deleted at every monthly cleanup or every 3 months. Deleted events can't be restored. Organization "
            "admins only."
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
                request.validated_data["delete_monthly"],
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
        return Response(
            OrganizationEventsRetentionSerializer(
                _organization_fields(organization_events_retention(self.organization))
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
            "Sets how long every project without its own window keeps events, and whether older events are deleted at "
            "every monthly cleanup or every 3 months. Deleted events can't be restored. Organization admins only."
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
                request.validated_data["delete_monthly"],
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages) from error
        return self._retention_response()
