from typing import Any

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.facade.suppression import (
    SUPPRESSION_SOURCE_CHOICES,
    Suppression,
    add_manual_suppression,
    list_active_suppressions,
    remove_suppression,
)


class SuppressionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MessageSuppressionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Server-assigned UUID for this suppression entry.")
    identifier = serializers.CharField(
        read_only=True,
        help_text="Normalized recipient email address. Suppression is keyed on this value, per team.",
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=SUPPRESSION_SOURCE_CHOICES,
        read_only=True,
        help_text="How the entry landed on the list: `BOUNCE` for automatic (bounce-driven), `COMPLAINT` for automatic (the recipient reported a message as spam), `MANUAL` for user-added via the UI/API.",
    )
    reason = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Human-readable reason for the suppression (e.g. 'Auto-suppressed after 5 consecutive soft bounces').",
    )
    transient_bounce_count = serializers.IntegerField(
        read_only=True,
        help_text="Rolling count of consecutive soft bounces with no successful delivery in between. Reset to 0 on any successful delivery. Ignored for MANUAL entries.",
    )
    last_bounce_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Timestamp of the most recent bounce, if any."
    )
    last_bounce_diagnostic = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="SMTP diagnostic string from the most recent bounce (e.g. '550 5.1.1 user unknown'), kept for visibility.",
    )
    suppressed = serializers.BooleanField(
        read_only=True,
        help_text="Whether the address is actively suppressed. A BOUNCE row can exist while still only counting bounces (suppressed=false) before it crosses the threshold.",
    )
    suppressed_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Timestamp when the address was first suppressed."
    )
    created_at = serializers.DateTimeField(
        read_only=True, help_text="When the row was first created (first bounce or manual add)."
    )
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the row was last touched by any write.")


class PaginatedMessageSuppressionSerializer(serializers.Serializer):
    """OpenAPI shape for the paginated suppressions response. Declared so drf-spectacular emits
    the {count, next, previous, results} envelope on the generated client, rather than a bare
    array — which the frontend actually receives at runtime."""

    count = serializers.IntegerField(help_text="Total number of suppressed recipients for the team.")
    next = serializers.URLField(allow_null=True, help_text="URL for the next page, or null on the last page.")
    previous = serializers.URLField(allow_null=True, help_text="URL for the previous page, or null on the first page.")
    results = MessageSuppressionSerializer(many=True)


class SuppressionsListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=512,
        help_text="Case-insensitive substring match on the recipient email address.",
    )


class AddSuppressionRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=512,
        help_text="The email address to suppress. Will not receive any messages until removed.",
    )


class MessageSuppressionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    Per-team email suppression list. Addresses here are skipped before send.

    Entries are added automatically after an address repeatedly soft-bounces, or manually by a
    user. This viewset lets users see and edit the list for full visibility.
    """

    scope_object = "hog_flow"
    # Custom actions must declare their write status so TeamAndOrgViewSetMixin's AccessControlPermission
    # checks hog_flow:write on the mutating endpoints. `suppressions` is scoped by its own
    # `required_scopes` instead, since it needs person:read on top of the workflow scope.
    scope_object_write_actions = ["add_suppression", "remove_suppression"]
    serializer_class = _FallbackSerializer

    @validated_request(
        query_serializer=SuppressionsListQuerySerializer,
        parameters=[
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiResponse(response=PaginatedMessageSuppressionSerializer)},
        summary="List suppressed email addresses for the team",
    )
    # The rows carry recipient email addresses and their SMTP diagnostics, so reading them is
    # person-data access on top of workflow read — same rationale as the `assets` and
    # `user_blast_radius` actions on HogFlowViewSet. Without `person:read` a workflow-only token
    # could enumerate who a team emails, and probe whether a given address is known by paging for
    # it. The UI uses session auth, which skips scope checks, so the suppression list is unaffected.
    @action(detail=False, methods=["get"], required_scopes=["hog_flow:read", "person:read"])
    def suppressions(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """List suppressed recipients for the team, most recently updated first."""
        # Resource-level check: `AccessControlPermission` only guarantees the caller has some
        # hog_flow object access. Since this endpoint returns team-wide data (every suppressed
        # recipient + their SMTP diagnostics) with no per-workflow object, require project-wide
        # hog_flow viewer access — otherwise a member granted access to a single workflow could
        # read the entire team's suppression list.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "viewer"):
            raise PermissionDenied("You need hog_flow viewer access to view the suppression list.")

        suppressions = list_active_suppressions(self.team_id, request.validated_query_data.get("search"))

        paginator = SuppressionPagination()
        # The paginator only needs len() and slicing, which the facade's sequence provides.
        page: list[Suppression] | None = paginator.paginate_queryset(suppressions, request)  # type: ignore[arg-type]
        if page is not None:
            serializer = MessageSuppressionSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = MessageSuppressionSerializer(suppressions, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=AddSuppressionRequestSerializer,
        responses={201: MessageSuppressionSerializer},
        summary="Manually add an email address to the suppression list",
    )
    @action(detail=False, methods=["post"])
    def add_suppression(self, request: Request, **kwargs: Any) -> Response:
        """Manually suppress an email address so no workflow sends to it."""
        # Team-wide mutation with no per-workflow object — require project-wide hog_flow editor
        # access. Otherwise an editor grant on one workflow could add arbitrary addresses to the
        # team's suppression list, blocking unrelated (including transactional) delivery.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise PermissionDenied("You need hog_flow editor access to modify the suppression list.")

        serializer = AddSuppressionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"].strip().lower()

        added = add_manual_suppression(self.team_id, identifier, request.user.id)

        response_status = status.HTTP_201_CREATED if added.created else status.HTTP_200_OK
        return Response(MessageSuppressionSerializer(added.suppression).data, status=response_status)

    @extend_schema(
        request=AddSuppressionRequestSerializer,
        responses={204: None},
        summary="Remove an email address from the suppression list",
    )
    @action(detail=False, methods=["post"])
    def remove_suppression(self, request: Request, **kwargs: Any) -> Response:
        """Remove an address from the suppression list so it can receive messages again."""
        # Same rationale as add_suppression — this is a team-wide mutation.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise PermissionDenied("You need hog_flow editor access to modify the suppression list.")

        serializer = AddSuppressionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"].strip().lower()

        if not remove_suppression(self.team_id, identifier):
            return Response({"error": "Suppression not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)
