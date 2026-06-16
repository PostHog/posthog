from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.unlayer import UnlayerNotConfiguredError, UnlayerRenderError, render_design_html


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


class MessageTemplatesViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]

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
