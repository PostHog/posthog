from typing import Any

from django.db.models import QuerySet

import structlog
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.team.team import Team

from products.field_notes.backend.models import FieldNote

logger = structlog.get_logger(__name__)


@extend_schema_field(
    {
        "type": "object",
        "nullable": True,
        "properties": {
            "width": {"type": "integer", "description": "Viewport width in pixels."},
            "height": {"type": "integer", "description": "Viewport height in pixels."},
        },
    }
)
class ViewportField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "description": "Structured element metadata: inferred selectors, attributes, and component hints.",
        "additionalProperties": True,
    }
)
class ElementContextField(serializers.JSONField):
    pass


class FieldNoteSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    # Length caps on free-text fields — the toolbar runs on untrusted customer pages, so cap
    # what it can POST to keep rows (and downstream MCP payloads) bounded.
    comment = serializers.CharField(max_length=5000, help_text="The note the user wrote about the element.")
    url = serializers.CharField(max_length=2048, help_text="Full URL of the page the field note was made on.")
    host = serializers.CharField(max_length=255, help_text="Hostname of the page, used to scope field notes to a site.")
    pathname = serializers.CharField(
        max_length=2048, required=False, allow_null=True, allow_blank=True, help_text="Path portion of the URL."
    )
    selector = serializers.CharField(max_length=4096, help_text="CSS selector that locates the element on the page.")
    element_text = serializers.CharField(
        max_length=2048,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Visible text of the element, if any.",
    )
    element_chain = serializers.CharField(
        max_length=20000,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Serialized autocapture-style element chain from the element up to the document root.",
    )
    field_note_status = serializers.ChoiceField(
        choices=FieldNote.Status.choices,
        required=False,
        help_text="Lifecycle of the field note: pending, acknowledged, resolved, or dismissed. Ignored on create.",
    )
    screenshot_url = serializers.CharField(
        max_length=2048,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="URL of an uploaded screenshot captured with the field_note.",
    )
    element_context = ElementContextField(
        required=False, help_text="Structured element metadata (inferred selectors, attributes, component hints)."
    )
    viewport = ViewportField(
        required=False, allow_null=True, help_text="Viewport size when the field note was made, as {width, height}."
    )

    class Meta:
        model = FieldNote
        fields = [
            "id",
            "comment",
            "field_note_status",
            "resolution",
            "url",
            "host",
            "pathname",
            "selector",
            "element_text",
            "element_chain",
            "element_context",
            "viewport",
            "screenshot_url",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

    def create(self, validated_data: dict[str, Any]) -> FieldNote:
        team = Team.objects.get(id=self.context["team_id"])
        request = self.context["request"]
        # Field notes are always born `pending`; status/resolution are agent-only and only
        # settable via update — strip them so a write-scoped toolbar token can't forge a
        # pre-resolved field note with a fabricated resolution note.
        validated_data.pop("field_note_status", None)
        validated_data.pop("resolution", None)
        field_note = FieldNote.objects.create(
            team=team,
            created_by=request.user if request.user.is_authenticated else None,
            **validated_data,
        )
        logger.info("field_note_created", id=field_note.id, team_id=team.id, host=field_note.host)
        return field_note


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "field_note_status",
                type=str,
                enum=FieldNote.Status.values,
                required=False,
                description="Filter to field notes in this lifecycle state (e.g. `pending` for unaddressed feedback).",
            ),
            OpenApiParameter(
                "host",
                type=str,
                required=False,
                description="Filter to field notes made on this hostname (e.g. `app.example.com`).",
            ),
        ]
    )
)
class FieldNoteViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update, and resolve toolbar field notes — UI feedback a user
    points at on their own site, surfaced to coding agents over MCP.
    """

    scope_object = "field_note"
    # `.unscoped()` avoids the fail-closed manager raising at import (no team context yet);
    # `safely_get_queryset` re-scopes every real query to the team.
    queryset = FieldNote.objects.unscoped()
    serializer_class = FieldNoteSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team_id=self.team_id)
        field_note_status = self.request.query_params.get("field_note_status")
        if field_note_status:
            if field_note_status not in FieldNote.Status.values:
                raise ValidationError({"field_note_status": f"Must be one of: {', '.join(FieldNote.Status.values)}"})
            queryset = queryset.filter(field_note_status=field_note_status)
        host = self.request.query_params.get("host")
        if host:
            queryset = queryset.filter(host=host)
        return queryset.order_by("-created_at")


# devex: coverage reporter demo touch — remove before merge
