from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import get_request_analytics_properties
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team.event_retention import events_retention_floor_date, events_retention_months_for_team
from posthog.models.user import User
from posthog.permissions import OrganizationAdminReadPermissions, OrganizationAdminWritePermissions

from products.product_analytics.backend.facade.contracts import OrganizationEventsRetention
from products.product_analytics.backend.facade.enums import EventsRetentionMonths
from products.product_analytics.backend.facade.events_retention import (
    NOT_A_STANDARD_PERIOD_MESSAGE,
    organization_downgrade_events_deleted,
    organization_events_deleted,
    organization_events_retention,
    project_events_deleted,
    project_events_retention,
    set_organization_events_retention,
    set_project_events_retention,
)
from products.product_analytics.backend.presentation.query_concurrency import query_concurrency_slots

EVENTS_RETENTION_DOCS_URL = "https://posthog.com/docs/data/events-retention"


def _retention_analytics_properties(request: Request) -> dict[str, object]:
    try:
        properties: dict[str, object] = {**get_request_analytics_properties(request)}
    except ValueError:
        properties = {}
    return {
        **properties,
        "$mcp_session_id": request.headers.get("X-Posthog-Mcp-Session-Id"),
        "$mcp_conversation_id": request.headers.get("X-Posthog-Mcp-Conversation-Id"),
        "$ai_trace_id": request.headers.get("X-PostHog-Trace-Id"),
    }


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
    retention_months_choices = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
        help_text="The periods, in months, an admin can choose from. A save also has to be between min_retention_months and max_retention_months. Only PostHog staff can set other periods.",
    )
    plan_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The longest period the organization's plan allows, in months.",
    )
    min_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The shortest period an admin can set, in months.",
    )
    max_retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The longest period an admin can set, in months. Never longer than the plan's period.",
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
        help_text="How many months of events stay queryable, counted back from today. Null while no retention period applies to the project.",
    )
    retained_from = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="The earliest date whose events are still queryable, in the project's timezone. Null while no retention period applies to the project.",
    )
    docs_url = serializers.URLField(
        read_only=True,
        help_text="Where the events retention policy is documented.",
    )
    project_retention_months = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="The period, in months, set for this project. Null while the project uses the organization's period.",
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
    retention_months = serializers.ChoiceField(
        choices=EventsRetentionMonths.choices,
        allow_null=True,
        error_messages={"invalid_choice": NOT_A_STANDARD_PERIOD_MESSAGE},
        help_text="The period in months. It also has to be between min_retention_months and max_retention_months. A shorter period deletes older events, and deleted events can't be restored. Null removes the period.",
    )


class EventsDeletedQuerySerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        min_value=1,
        max_value=1200,
        help_text="The period in months to count for, at most 1200. Only events older than this period are counted.",
    )


class EventsDeletedSerializer(serializers.Serializer):
    retention_months = serializers.IntegerField(
        read_only=True,
        help_text="The period in months that was counted for.",
    )
    events_deleted = serializers.IntegerField(
        read_only=True,
        help_text=(
            "How many queryable events are older than the cutoff for this period. The endpoint says which "
            "deletion sets the cutoff. The count can be up to a day old."
        ),
    )


def _events_deleted_response(months: int, events_deleted: int) -> Response:
    return Response(EventsDeletedSerializer({"retention_months": months, "events_deleted": events_deleted}).data)


def _organization_fields(organization: OrganizationEventsRetention) -> dict[str, Any]:
    return {
        "organization_retention_months": organization.organization_months,
        "default_retention_months": organization.default_months,
        "default_is_grandfathered": organization.default_is_grandfathered,
        "retention_months_choices": organization.months_choices,
        "plan_retention_months": organization.plan_months,
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
        summary="Get the events retention period for a project",
        description=(
            "Returns how far back events stay queryable for this project, the periods set for the project and its "
            "organization, the periods an admin can set, and the project's next deletion. Both queryable period fields "
            "are null while no retention period applies to the project."
        ),
        responses={200: EventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._retention_response()

    @validated_request(
        EventsRetentionUpdateSerializer,
        operation_id="events_retention_update",
        summary="Set the events retention period for a project",
        description=(
            "Sets how long this project keeps events, overriding the organization's period. The period has to be one "
            "of retention_months_choices. Older events are deleted at the next monthly cleanup and can't be restored. "
            "Organization admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsRetentionSerializer, description="The project's new period."),
            400: OpenApiResponse(description="The period isn't one of the periods an admin can set."),
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
                analytics_properties=_retention_analytics_properties(request),
            )
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages) from error
        return self._retention_response()

    @validated_request(
        query_serializer=EventsDeletedQuerySerializer,
        operation_id="events_retention_deletion_count",
        summary="Count the events a project's period would delete",
        description=(
            "Counts the project's events that the next monthly cleanup deletes if the project keeps events for "
            "retention_months. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsDeletedSerializer, description="The count."),
            403: OpenApiResponse(description="The user isn't an organization admin."),
            504: OpenApiResponse(description="The count took too long."),
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="deletion_count",
        required_scopes=["project:read", "query:read"],
        permission_classes=[OrganizationAdminReadPermissions],
    )
    def deletion_count(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        months = request.validated_query_data["retention_months"]
        return _events_deleted_response(
            months, project_events_deleted(self.team, months, concurrency_slots=query_concurrency_slots)
        )


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
        summary="Get the organization's events retention period",
        description=(
            "Returns the events retention period that every project without its own period uses, the default period "
            "while none is set, and the periods an organization admin can set."
        ),
        responses={200: OrganizationEventsRetentionSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._retention_response()

    @validated_request(
        EventsRetentionUpdateSerializer,
        operation_id="organization_events_retention_update",
        summary="Set the organization's events retention period",
        description=(
            "Sets how long every project without its own period keeps events. The period has to be one of "
            "retention_months_choices. Older events are deleted at the next monthly cleanup and can't be restored. "
            "Organization admins only."
        ),
        responses={
            200: OpenApiResponse(
                response=OrganizationEventsRetentionSerializer, description="The organization's new period."
            ),
            400: OpenApiResponse(description="The period isn't one of the periods an admin can set."),
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
                analytics_properties=_retention_analytics_properties(request),
            )
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages) from error
        return self._retention_response()

    @validated_request(
        query_serializer=EventsDeletedQuerySerializer,
        operation_id="organization_events_retention_deletion_count",
        summary="Count the events the organization's period would delete",
        description=(
            "Counts the events that the next monthly cleanup deletes if the organization keeps events for "
            "retention_months, summed over the projects without their own period. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsDeletedSerializer, description="The count."),
            403: OpenApiResponse(description="The user isn't an organization admin."),
            504: OpenApiResponse(description="The count took too long."),
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="deletion_count",
        required_scopes=["organization:read", "query:read"],
        permission_classes=[OrganizationAdminReadPermissions],
    )
    def deletion_count(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        months = request.validated_query_data["retention_months"]
        return _events_deleted_response(
            months, organization_events_deleted(self.organization, months, concurrency_slots=query_concurrency_slots)
        )

    @validated_request(
        query_serializer=EventsDeletedQuerySerializer,
        operation_id="organization_events_retention_downgrade_deletion_count",
        summary="Count the events a downgrade to a shorter period would delete",
        description=(
            "Counts the events that the deletion pass after a plan downgrade deletes if the organization's events "
            "retention drops to retention_months, whether or not deletion is rolled out to the organization yet. Sums "
            "the projects whose period is longer than retention_months. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsDeletedSerializer, description="The count."),
            403: OpenApiResponse(description="The user isn't an organization admin."),
            504: OpenApiResponse(description="The count took too long."),
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="downgrade_deletion_count",
        required_scopes=["organization:read", "query:read"],
        permission_classes=[OrganizationAdminReadPermissions],
    )
    def downgrade_deletion_count(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        months = request.validated_query_data["retention_months"]
        return _events_deleted_response(
            months,
            organization_downgrade_events_deleted(self.organization, months, concurrency_slots=query_concurrency_slots),
        )
