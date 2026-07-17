from typing import Any

from django.db.models import F
from django.db.models.functions import Coalesce, Now
from django.utils import timezone

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource


class SuppressionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MessageSuppressionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageSuppression
        fields = [
            "id",
            "identifier",
            "source",
            "reason",
            "transient_bounce_count",
            "last_bounce_at",
            "last_bounce_diagnostic",
            "suppressed",
            "suppressed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Server-assigned UUID for this suppression entry."},
            "identifier": {
                "help_text": "Normalized recipient email address. Suppression is keyed on this value, per team."
            },
            "source": {
                "help_text": "How the entry landed on the list: `BOUNCE` for automatic (bounce-driven), `MANUAL` for user-added via the UI/API."
            },
            "reason": {
                "help_text": "Human-readable reason for the suppression (e.g. 'Auto-suppressed after 5 consecutive soft bounces')."
            },
            "transient_bounce_count": {
                "help_text": "Rolling count of consecutive soft bounces with no successful delivery in between. Reset to 0 on any successful delivery. Ignored for MANUAL entries."
            },
            "last_bounce_at": {"help_text": "Timestamp of the most recent bounce, if any."},
            "last_bounce_diagnostic": {
                "help_text": "SMTP diagnostic string from the most recent bounce (e.g. '550 5.1.1 user unknown'), kept for visibility."
            },
            "suppressed": {
                "help_text": "Whether the address is actively suppressed. A BOUNCE row can exist while still only counting bounces (suppressed=false) before it crosses the threshold."
            },
            "suppressed_at": {"help_text": "Timestamp when the address was first suppressed."},
            "created_at": {"help_text": "When the row was first created (first bounce or manual add)."},
            "updated_at": {"help_text": "When the row was last touched by any write."},
        }


class PaginatedMessageSuppressionSerializer(serializers.Serializer):
    """OpenAPI shape for the paginated suppressions response. Declared so drf-spectacular emits
    the {count, next, previous, results} envelope on the generated client, rather than a bare
    array — which the frontend actually receives at runtime."""

    count = serializers.IntegerField(help_text="Total number of suppressed recipients for the team.")
    next = serializers.URLField(allow_null=True, help_text="URL for the next page, or null on the last page.")
    previous = serializers.URLField(allow_null=True, help_text="URL for the previous page, or null on the first page.")
    results = MessageSuppressionSerializer(many=True)


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
    # checks hog_flow:write on the mutating endpoints; the default 'suppressions' list stays a read.
    scope_object_write_actions = ["add_suppression", "remove_suppression"]
    serializer_class = _FallbackSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={200: PaginatedMessageSuppressionSerializer},
        summary="List suppressed email addresses for the team",
    )
    @action(detail=False, methods=["get"])
    def suppressions(self, request: Request, **kwargs: Any) -> Response:
        """List suppressed recipients for the team, most recently updated first."""
        suppressions = (
            MessageSuppression.objects.for_team(self.team_id)
            .filter(suppressed=True, deleted=False)
            .order_by("-updated_at")
        )

        paginator = SuppressionPagination()
        page = paginator.paginate_queryset(suppressions, request)
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
        serializer = AddSuppressionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"].strip().lower()

        suppression, created = MessageSuppression.objects.for_team(self.team_id).get_or_create(
            team_id=self.team_id,
            identifier=identifier,
            defaults={
                "created_by": request.user,
                "source": SuppressionSource.MANUAL,
                "suppressed": True,
                "suppressed_at": timezone.now(),
                "reason": "Manually added",
            },
        )

        if not created:
            # Re-suppress (and un-delete) an existing row, e.g. one that had only been counting
            # bounces or was previously removed. Coalesce lets Postgres preserve an existing
            # suppressed_at atomically, so two concurrent add_suppression calls can't both compute
            # their own now() and overwrite each other.
            MessageSuppression.objects.for_team(self.team_id).filter(pk=suppression.pk).update(
                suppressed=True,
                suppressed_at=Coalesce(F("suppressed_at"), Now()),
                source=SuppressionSource.MANUAL,
                reason="Manually added",
                deleted=False,
                updated_at=Now(),
            )
            suppression.refresh_from_db()

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(MessageSuppressionSerializer(suppression).data, status=response_status)

    @extend_schema(
        request=AddSuppressionRequestSerializer,
        responses={204: None},
        summary="Remove an email address from the suppression list",
    )
    @action(detail=False, methods=["post"])
    def remove_suppression(self, request: Request, **kwargs: Any) -> Response:
        """Remove an address from the suppression list so it can receive messages again."""
        serializer = AddSuppressionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"].strip().lower()

        # Soft-delete and un-suppress. Reset the bounce counter so a previously-dead address that
        # a user deliberately re-enables starts from a clean slate. `source` is reset to BOUNCE so
        # a future auto-suppression can re-suppress this row — the node upserts skip rows with
        # source='MANUAL' (to protect user-managed entries), so a removed MANUAL row would otherwise
        # be permanently invisible to the bounce-driven write path.
        updated = (
            MessageSuppression.objects.for_team(self.team_id)
            .filter(identifier=identifier)
            .update(
                suppressed=False,
                deleted=True,
                transient_bounce_count=0,
                source=SuppressionSource.BOUNCE,
                updated_at=timezone.now(),
            )
        )

        if not updated:
            return Response({"error": "Suppression not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)
