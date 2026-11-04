from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
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
    organization_events_deleted_by_retention,
    organization_events_retention,
    project_events_deleted_by_retention,
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
        help_text="The period, in months, that every project without its own period uses. Null while those projects use the default period.",
    )
    default_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The period, in months, that projects use while no period is set for them or their organization. 24 months on current plans, never longer than the plan's period and never shorter than the shortest period an admin can set. Plans from before the 24-month default use the plan's period.",
    )
    default_is_grandfathered = serializers.BooleanField(
        read_only=True,
        help_text="Whether the default is longer than 24 months because the plan predates the 24-month default.",
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
    retention_months_choices = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
        help_text="The periods, in months, an admin can set: 1, 3, 12, 24, 60 or 84, limited to the range an admin can set. Only PostHog staff can set other values.",
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
    scheduled_pass_on = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="The next cleanup every 3 months that deletes this project's events past its current period. Null while the project has none scheduled.",
    )
    first_pass_on = serializers.DateField(
        read_only=True,
        help_text="The earliest cleanup every 3 months for a period that gets shorter today.",
    )
    default_period_deletes = serializers.BooleanField(
        read_only=True,
        help_text="Whether the cleanup deletes this project's events past the default period while no period is set.",
    )


class EventsRetentionUpdateSerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        allow_null=True,
        min_value=1,
        help_text="The period in months. Has to be one of retention_months_choices unless you are PostHog staff. Older events are not deleted at once. Deletion runs once a month. Null removes the period.",
    )


def _organization_fields(organization: OrganizationEventsRetention) -> dict[str, Any]:
    return {
        "organization_retention_months": organization.organization_months,
        "default_retention_months": organization.default_months,
        "default_is_grandfathered": organization.default_is_grandfathered,
        "plan_retention_months": organization.plan_months,
        "min_retention_months": organization.min_months,
        "max_retention_months": organization.max_months,
        "retention_months_choices": organization.choice_months,
        "next_monthly_cleanup_on": organization.next_cleanup_on,
    }


class EventsRetentionImpactQuerySerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        min_value=1,
        help_text="The period in months to count events for.",
    )


class EventsRetentionImpactSerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The period in months that the count is for.",
    )
    events_deleted = serializers.IntegerField(
        read_only=True,
        help_text="How many events the monthly cleanup would delete if it ran now with this period. Cached for up to a day.",
    )


def _impact_response(months: int, events_deleted: int) -> Response:
    return Response(
        EventsRetentionImpactSerializer({"retention_months": months, "events_deleted": events_deleted}).data
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
        project = project_events_retention(self.team)
        return Response(
            EventsRetentionSerializer(
                {
                    "retention_months": retention_months,
                    "retained_from": retained_from,
                    "docs_url": EVENTS_RETENTION_DOCS_URL,
                    "project_retention_months": project.project_months,
                    "next_deletion_on": project.next_deletion.deletes_on if project.next_deletion else None,
                    "next_deletion_before": project.next_deletion.deletes_before if project.next_deletion else None,
                    "scheduled_pass_on": project.scheduled_pass_on,
                    "first_pass_on": project.first_pass_on,
                    "default_period_deletes": project.default_period_deletes,
                    **_organization_fields(organization_events_retention(self.organization)),
                }
            ).data
        )

    @extend_schema(
        operation_id="events_retention_retrieve",
        summary="Get the events retention window for a project",
        description=(
            "Returns how far back events stay queryable for this project, the windows set for the project and its "
            "organization, the range an admin can set, and the project's next deletion. Both queryable period fields "
            "are null while no retention period applies to the project."
        ),
        responses={200: EventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._retention_response()

    @validated_request(
        query_serializer=EventsRetentionImpactQuerySerializer,
        operation_id="events_retention_impact",
        summary="Count the project events a retention period would delete",
        description=(
            "Returns how many of this project's events the monthly cleanup would delete if it ran now with the "
            "given period. The count is cached for up to a day."
        ),
        responses={200: OpenApiResponse(response=EventsRetentionImpactSerializer)},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def impact(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        months = request.validated_query_data["retention_months"]
        return _impact_response(months, project_events_deleted_by_retention(self.team, months))

    @validated_request(
        EventsRetentionUpdateSerializer,
        operation_id="events_retention_update",
        summary="Set the events retention window for a project",
        description=(
            "Sets how long this project keeps events, overriding the organization's period. The period has to be one "
            "of retention_months_choices unless you are PostHog staff. Older events are not deleted at once. Deletion "
            "runs once a month. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsRetentionSerializer, description="The project's new window."),
            400: OpenApiResponse(description="The period is not one of the choices an admin can set."),
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
        return Response(
            OrganizationEventsRetentionSerializer(
                _organization_fields(organization_events_retention(self.organization))
            ).data
        )

    @extend_schema(
        operation_id="organization_events_retention_retrieve",
        summary="Get the organization's events retention window",
        description=(
            "Returns the events retention period that every project without its own period uses, the default period "
            "while none is set, and the range an organization admin can set."
        ),
        responses={200: OrganizationEventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._retention_response()

    @validated_request(
        query_serializer=EventsRetentionImpactQuerySerializer,
        operation_id="organization_events_retention_impact",
        summary="Count the events an organization retention period would delete",
        description=(
            "Returns how many events the monthly cleanup would delete if it ran now with the given period, across "
            "the projects that use the organization's period. The count is cached for up to a day."
        ),
        responses={200: OpenApiResponse(response=EventsRetentionImpactSerializer)},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def impact(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        months = request.validated_query_data["retention_months"]
        return _impact_response(months, organization_events_deleted_by_retention(self.organization, months))

    @validated_request(
        EventsRetentionUpdateSerializer,
        operation_id="organization_events_retention_update",
        summary="Set the organization's events retention window",
        description=(
            "Sets how long every project without its own period keeps events. The period has to be one of "
            "retention_months_choices unless you are PostHog staff. Older events are not deleted at once. Deletion "
            "runs once a month. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(
                response=OrganizationEventsRetentionSerializer, description="The organization's new window."
            ),
            400: OpenApiResponse(description="The period is not one of the choices an admin can set."),
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
