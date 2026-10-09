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
from posthog.cdp.validation import build_html_wrap_design
from posthog.event_usage import report_user_action

from products.messaging.backend.facade.api import (
    UnlayerNotConfiguredError,
    UnlayerRenderError,
    apply_design_operations,
    render_design_html,
    validate_design,
)
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.presentation.views.serializers import DesignOperationSerializer
from products.notifications.backend.facade.api import publish_resource_edited

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
        # Programmatically authored templates often supply html without a design, which the
        # visual editor can't open. Wrap the html in a single custom HTML block; the stored
        # html stays untouched, so nothing about the sent email changes.
        if email and email.get("html") and not email.get("design"):
            email["design"] = build_html_wrap_design(email["html"])
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

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        instance: MessageTemplate = serializer.save()
        # report_user_action injects source and MCP-client properties from the request, so a create from the
        # visual editor and one from the agent count in the same metric. Capture must never break the request.
        try:
            report_user_action(
                self.request.user,
                "message_template_created",
                {
                    "template_id": str(instance.id),
                    "team_id": str(self.team_id),
                    "organization_id": str(self.organization_id),
                },
                team=self.team,
                # Without this the event groups by the person's current organization, which can differ
                # from the route's when they belong to more than one.
                organization=self.organization,
                request=self.request,
            )
        except Exception as e:
            logger.warning("Failed to capture message template usage event", error=str(e))

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        instance: MessageTemplate = serializer.save()
        self._emit_resource_edited(instance)

    def _emit_resource_edited(self, instance: MessageTemplate) -> None:
        # Realtime "edited elsewhere" signal so an open editor can refresh instead of overwriting a write
        # from another channel (UI/MCP/API). Fires for every channel; the frontend drops its own echo by
        # comparing updated_at. Transient, so no inbox notification. The write is already committed when
        # this runs, so a publish failure must not turn a saved template into an error response.
        try:
            publish_resource_edited(
                team=self.team,
                resource_type="MessageTemplate",
                resource_id=str(instance.id),
                updated_at=instance.updated_at.isoformat(),
                actor_user_id=getattr(self.request.user, "id", None),
                ac_resource_type=self.scope_object,
            )
        except Exception as e:
            logger.warning("Failed to publish message template edited event", error=str(e))

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

        self._emit_resource_edited(locked)
        return Response(self.get_serializer(locked).data)
