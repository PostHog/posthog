from typing import Any

from django.db.models import QuerySet

import structlog
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.team.team import Team

from products.toolbar_annotations.backend.models import ToolbarAnnotation

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


class ToolbarAnnotationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    # Length caps on free-text fields — the toolbar runs on untrusted customer pages, so cap
    # what it can POST to keep rows (and downstream MCP payloads) bounded.
    comment = serializers.CharField(max_length=5000, help_text="The annotation note the user wrote about the element.")
    url = serializers.CharField(max_length=2048, help_text="Full URL of the page the annotation was made on.")
    host = serializers.CharField(max_length=255, help_text="Hostname of the page, used to scope annotations to a site.")
    pathname = serializers.CharField(
        max_length=2048, required=False, allow_null=True, allow_blank=True, help_text="Path portion of the URL."
    )
    selector = serializers.CharField(
        max_length=4096, help_text="CSS selector that locates the annotated element on the page."
    )
    element_text = serializers.CharField(
        max_length=2048,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Visible text of the annotated element, if any.",
    )
    element_chain = serializers.CharField(
        max_length=20000,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Serialized autocapture-style element chain from the element up to the document root.",
    )
    annotation_status = serializers.ChoiceField(
        choices=ToolbarAnnotation.Status.choices,
        required=False,
        help_text="Lifecycle of the annotation: pending, acknowledged, resolved, or dismissed. Ignored on create.",
    )
    element_context = ElementContextField(
        required=False, help_text="Structured element metadata (inferred selectors, attributes, component hints)."
    )
    viewport = ViewportField(
        required=False, allow_null=True, help_text="Viewport size when the annotation was made, as {width, height}."
    )

    class Meta:
        model = ToolbarAnnotation
        fields = [
            "id",
            "comment",
            "annotation_status",
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

    def create(self, validated_data: dict[str, Any]) -> ToolbarAnnotation:
        team = Team.objects.get(id=self.context["team_id"])
        request = self.context["request"]
        # Annotations are always born `pending`; status/resolution are agent-only and only
        # settable via update — strip them so a write-scoped toolbar token can't forge a
        # pre-resolved annotation with a fabricated resolution note.
        validated_data.pop("annotation_status", None)
        validated_data.pop("resolution", None)
        annotation = ToolbarAnnotation.objects.create(
            team=team,
            created_by=request.user if request.user.is_authenticated else None,
            **validated_data,
        )
        logger.info("toolbar_annotation_created", id=annotation.id, team_id=team.id, host=annotation.host)
        return annotation


class ToolbarAnnotationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update, and resolve toolbar annotations — UI feedback a user
    points at on their own site, surfaced to coding agents over MCP.
    """

    scope_object = "toolbar_annotation"
    # `.unscoped()` avoids the fail-closed manager raising at import (no team context yet);
    # `safely_get_queryset` re-scopes every real query to the team.
    queryset = ToolbarAnnotation.objects.unscoped()
    serializer_class = ToolbarAnnotationSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team_id=self.team_id)
        annotation_status = self.request.query_params.get("annotation_status")
        if annotation_status:
            if annotation_status not in ToolbarAnnotation.Status.values:
                raise ValidationError(
                    {"annotation_status": f"Must be one of: {', '.join(ToolbarAnnotation.Status.values)}"}
                )
            queryset = queryset.filter(annotation_status=annotation_status)
        host = self.request.query_params.get("host")
        if host:
            queryset = queryset.filter(host=host)
        return queryset.order_by("-created_at")
