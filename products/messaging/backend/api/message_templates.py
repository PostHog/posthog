from copy import deepcopy
from typing import Any

from django.db import transaction

import structlog
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer

from products.messaging.backend.api.design_operations import apply_design_operations
from products.messaging.backend.api.design_validation import validate_design
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.unlayer import UnlayerNotConfiguredError, UnlayerRenderError, render_design_html

logger = structlog.get_logger(__name__)


# Shallow skeleton of the Unlayer design document — enough structure for API callers
# (and the LLMs behind MCP tools) to author against; the full row/column/content
# shape is documented in the designing-email-templates skill.
@extend_schema_field(
    {
        "type": "object",
        "properties": {
            "counters": {
                "type": "object",
                "description": 'Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}.',
            },
            "schemaVersion": {"type": "integer", "description": "Design schema version, e.g. 16."},
            "body": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Any unique string."},
                    "rows": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}.",
                    },
                    "headers": {"type": "array", "items": {"type": "object"}},
                    "footers": {"type": "array", "items": {"type": "object"}},
                    "values": {
                        "type": "object",
                        "description": "Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor.",
                    },
                },
                "required": ["rows"],
            },
        },
        "required": ["body", "schemaVersion"],
    }
)
class UnlayerDesignField(serializers.JSONField):
    pass


class EmailTemplateSerializer(serializers.Serializer):
    subject = serializers.CharField(
        required=False,
        help_text="Email subject line. Supports Liquid templating. Required for email-type templates.",
    )
    text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Plain-text fallback body for clients that can't render the email.",
    )
    html = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Rendered email body — derived from the design at save time. "
        "The visual editor's save path supplies it directly; omit it otherwise.",
    )
    design = UnlayerDesignField(
        required=False,
        help_text="Design JSON for PostHog's visual email editor — the authoring surface and source of "
        "truth. The server renders the sent email from it, and it opens as editable blocks in the editor. "
        "Full schema in the designing-email-templates skill.",
    )


class MessageTemplateContentSerializer(serializers.Serializer):
    templating = serializers.ChoiceField(
        choices=["liquid"],
        default="liquid",
        help_text="Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.",
    )
    email = EmailTemplateSerializer(
        required=False,
        allow_null=True,
        help_text="Email message content. Replaced as a whole on update — send the complete object.",
    )


class MessageTemplateSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    content = MessageTemplateContentSerializer(
        required=False,
        help_text="Template content keyed by channel. Replaced as a whole on update, not merged.",
    )
    message_category = TeamScopedPrimaryKeyRelatedField(
        queryset=MessageCategory.objects.all(),
        required=False,
        allow_null=True,
        help_text="Message category ID to file the template under. Must belong to the same project.",
    )

    class Meta:
        model = MessageTemplate
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "updated_at",
            "content",
            "created_by",
            "type",
            "message_category",
            "deleted",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Human-readable template name shown in the library."},
            "description": {"help_text": "What the template is for and when to use it."},
            "type": {"help_text": "Message channel of the template. Currently 'email'."},
            "deleted": {"help_text": "Soft-delete flag. Set true to remove the template from the library."},
        }

    def validate(self, data: Any) -> Any:
        template_type = data.get("type")
        email = data.get("content", {}).get("email") if data.get("content") else None
        if template_type == "email" and email and not email.get("subject"):
            raise serializers.ValidationError(
                {"content": {"email": {"subject": "Subject is required for email templates."}}}
            )
        # Design-only saves get their html rendered server-side (the send path uses html
        # verbatim). A submitted html is trusted as-is — that's the visual editor's own export.
        if email and email.get("design") and not email.get("html"):
            try:
                email["html"] = render_design_html(email["design"])
            except UnlayerNotConfiguredError:
                raise serializers.ValidationError(
                    {
                        "content": {
                            "email": {
                                "design": "Design rendering is not configured on this instance — an administrator "
                                "must set UNLAYER_API_KEY to enable saving design-authored templates."
                            }
                        }
                    }
                )
            except UnlayerRenderError as e:
                raise serializers.ValidationError(
                    {"content": {"email": {"design": f"Rendering the design to HTML failed: {e}"}}}
                )
        return data

    def create(self, validated_data: Any) -> Any:
        request = self.context["request"]
        team_id = self.context["team_id"]

        instance = MessageTemplate.objects.create(**validated_data, team_id=team_id, created_by=request.user)
        return instance


DESIGN_OPERATION_TYPES = [
    "update_content",
    "update_column",
    "update_row",
    "update_body",
    "add_content",
    "remove_content",
    "move_content",
    "add_row",
    "remove_row",
]

# Per-op required fields, validated in DesignOperationSerializer.validate so a malformed op is rejected
# before any are applied (the whole batch is atomic).
_DESIGN_OPERATION_REQUIRED_FIELDS: dict[str, list[str]] = {
    "update_content": ["id", "patch"],
    "update_column": ["id", "patch"],
    "update_row": ["id", "patch"],
    "update_body": ["patch"],
    "add_content": ["column_id", "content"],
    "remove_content": ["id"],
    "move_content": ["id", "column_id"],
    "add_row": ["row"],
    "remove_row": ["id"],
}


class DesignOperationSerializer(serializers.Serializer):
    op = serializers.ChoiceField(
        choices=DESIGN_OPERATION_TYPES,
        help_text=(
            "Design edit. update_content {id, patch}: deep-merge patch into the content block's fields (a null "
            "leaf deletes that key) — the surgical path, e.g. change just values.text. update_row / update_column "
            "{id, patch} and update_body {patch}: same deep-merge for row/column/body-level settings. add_content "
            "{column_id, content, index?}: insert a content block into a column (id and Unlayer numbering are "
            "filled in for you). remove_content {id} / move_content {id, column_id, index?}: delete or relocate a "
            "block. add_row {row, index?} / remove_row {id}: add or delete a row."
        ),
    )
    id = serializers.CharField(
        required=False,
        help_text="Target node id. Required for update_content/column/row, remove_content, remove_row, move_content.",
    )
    column_id = serializers.CharField(
        required=False, help_text="Target column id. Required for add_content and move_content."
    )
    patch = serializers.JSONField(
        required=False,
        help_text=(
            "update_* only. Partial fields deep-merged into the existing node; a null leaf deletes that key. "
            "e.g. {values: {text: '<p>Hi</p>'}} changes only the block's text."
        ),
    )
    content = serializers.JSONField(
        required=False,
        help_text=(
            "add_content only. A content block {type, values: {...}}; omit id and values._meta — they're assigned "
            "server-side. type is one of text, heading, button, image, divider, html, etc."
        ),
    )
    row = serializers.JSONField(
        required=False,
        help_text=(
            "add_row only. A full row {cells, columns: [{contents: [...], values}], values}; ids and Unlayer "
            "numbering are assigned server-side for the row and everything nested in it."
        ),
    )
    index = serializers.IntegerField(
        required=False,
        help_text="add_*/move_content only. 0-based insert position; omit to append to the end.",
    )

    def validate(self, data: Any) -> Any:
        op = data["op"]
        missing = [field for field in _DESIGN_OPERATION_REQUIRED_FIELDS[op] if data.get(field) is None]
        if missing:
            raise serializers.ValidationError(f"op '{op}' requires: {', '.join(missing)}")
        if op in ("update_content", "update_column", "update_row", "update_body") and not isinstance(
            data.get("patch"), dict
        ):
            raise serializers.ValidationError(f"{op} 'patch' must be an object")
        if op == "add_content" and not isinstance(data.get("content"), dict):
            raise serializers.ValidationError("add_content 'content' must be an object")
        if op == "add_row" and not isinstance(data.get("row"), dict):
            raise serializers.ValidationError("add_row 'row' must be an object")
        return data


class DesignPatchSerializer(serializers.Serializer):
    operations = serializers.ListField(
        child=DesignOperationSerializer(),
        allow_empty=False,
        help_text=(
            "Ordered edits applied atomically to a template's Unlayer design: the stored design is read, the ops "
            "are applied in order, the result is validated and re-rendered to HTML, and it's saved only if valid — "
            "otherwise the template is unchanged. Reference blocks by id so you never resend the whole design."
        ),
    )


class MessageTemplatesViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    # `design` is a custom write action; list it so programmatic callers (MCP/personal API key) get
    # hog_flow:write checked instead of being rejected as an action with no declared scope.
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "design"]

    serializer_class = MessageTemplateSerializer
    queryset = MessageTemplate.objects.all()

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(
                team_id=self.team_id,
                deleted=False,
            )
            .select_related("created_by")
            .order_by("-created_at")
        )

    @extend_schema(request=DesignPatchSerializer, responses={200: MessageTemplateSerializer})
    @action(detail=True, methods=["PATCH"])
    def design(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Surgical design editing: apply a small, id-addressed op list to the stored Unlayer design instead
        # of re-transmitting the whole design JSON. Reads, applies, validates, re-renders, and saves
        # atomically so a rejected batch leaves the template untouched (and concurrent visual-editor saves
        # can't interleave).
        op_serializer = DesignPatchSerializer(data=request.data)
        op_serializer.is_valid(raise_exception=True)
        operations = op_serializer.validated_data["operations"]

        # Authorize + team-scope via the normal lookup, then re-read FOR UPDATE inside the transaction.
        instance = self.get_object()

        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance, locked for update)
            locked = MessageTemplate.objects.select_for_update().get(pk=instance.pk)

            content = deepcopy(locked.content or {})
            email = content.get("email") or {}
            design = email.get("design")
            if not isinstance(design, dict):
                raise serializers.ValidationError(
                    {
                        "design": "This template has no editable design JSON to patch. Set content.email.design "
                        "with a full update first, then use surgical operations."
                    }
                )

            new_design = apply_design_operations(design, operations)
            for warning in validate_design(new_design):
                logger.info("email_template_design_warning", warning=warning, template_id=str(locked.id))

            email["design"] = new_design
            # Drop html so the serializer re-renders it from the patched design (its design->html path).
            email.pop("html", None)
            content["email"] = email

            serializer = self.get_serializer(locked, data={"content": content}, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()

        return Response(self.get_serializer(locked).data)
