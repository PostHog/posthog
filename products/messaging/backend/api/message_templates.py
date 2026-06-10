from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_template import MessageTemplate


@extend_schema_field(OpenApiTypes.OBJECT)
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
        help_text="Plain-text fallback body, sent alongside the HTML.",
    )
    html = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Full HTML document sent verbatim as the email body. Supports Liquid templating.",
    )
    design = UnlayerDesignField(
        required=False,
        help_text="Unlayer design JSON saved by the in-app visual editor; present only on editor-authored templates.",
    )


class MessageTemplateContentSerializer(serializers.Serializer):
    templating = serializers.ChoiceField(
        choices=["hog", "liquid"],
        required=False,
        help_text="Templating language for subject/html/text. Use 'liquid' for new templates.",
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
