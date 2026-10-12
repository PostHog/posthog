from collections.abc import Sequence
from dataclasses import fields as dataclass_fields
from types import SimpleNamespace
from typing import Any

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.cdp.validation import build_html_wrap_design
from posthog.event_usage import report_user_action
from posthog.models import User

from products.messaging.backend.facade.api import (
    UnlayerNotConfiguredError,
    UnlayerRenderError,
    apply_design_operations,
    render_design_html,
    validate_design,
)
from products.messaging.backend.facade.templates import (
    MessageCategoryNotInTeam,
    MessageTemplateMissing,
    MessageTemplateRow,
    create_template,
    edit_template_content,
    get_template,
    list_templates,
    team_category_id,
    update_template,
)
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


@extend_schema_field(OpenApiTypes.UUID)
class MessageTemplateCategoryField(serializers.Field):
    """A category id that must belong to the template's team. Errors match a primary key related field."""

    default_error_messages = serializers.PrimaryKeyRelatedField.default_error_messages

    def run_validation(self, data: Any = serializers.empty) -> Any:
        # A DRF related field reads an empty string as null, and clients send "" to clear the category.
        if data == "":
            data = None
        return super().run_validation(data)

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, bool):
            self.fail("incorrect_type", data_type=type(data).__name__)
        try:
            return team_category_id(self.context["team_id"], data)
        except MessageCategoryNotInTeam:
            self.fail("does_not_exist", pk_value=data)
        except (TypeError, ValueError):
            self.fail("incorrect_type", data_type=type(data).__name__)

    def to_representation(self, value: Any) -> Any:
        return value


class MessageTemplateSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=400, help_text="Human-readable template name shown in the library.")
    description = serializers.CharField(
        allow_blank=True,
        required=False,
        style={"base_template": "textarea.html"},
        help_text="What the template is for and when to use it.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    content = MessageTemplateContentSerializer(
        required=False,
        help_text="Template content keyed by channel. Replaced as a whole on update, not merged.",
    )
    created_by = UserBasicSerializer(read_only=True)
    type = serializers.CharField(
        max_length=24,
        allow_blank=True,
        required=False,
        help_text="Message channel of the template. Currently 'email'.",
    )
    message_category = MessageTemplateCategoryField(
        required=False,
        allow_null=True,
        help_text="Message category ID to file the template under. Must belong to the same project.",
    )
    deleted = serializers.BooleanField(
        required=False, help_text="Soft-delete flag. Set true to remove the template from the library."
    )

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


TEMPLATE_ID_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="A UUID string identifying this message template.",
)


@extend_schema_view(
    retrieve=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
    update=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
    partial_update=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
    destroy=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
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

    def dangerously_get_object(self) -> MessageTemplateRow:
        # Team scoping happens in the facade lookup, because the view has no queryset to filter.
        # DRF's detail OPTIONS metadata also calls get_object(), so the lookup must live here.
        try:
            template = get_template(self.team_id, self.kwargs["pk"])
        except MessageTemplateMissing:
            raise NotFound()
        self.check_object_permissions(self.request, template)
        return template

    def _with_creators(self, templates: Sequence[MessageTemplateRow]) -> list[SimpleNamespace]:
        creator_ids = {template.created_by_id for template in templates if template.created_by_id}
        creators = {user.id: user for user in User.objects.filter(id__in=creator_ids)} if creator_ids else {}
        return [
            SimpleNamespace(
                **{field.name: getattr(template, field.name) for field in dataclass_fields(template)},
                created_by=creators.get(template.created_by_id) if template.created_by_id else None,
                message_category=template.message_category_id,
            )
            for template in templates
        ]

    def _serialize(self, template: MessageTemplateRow) -> Any:
        return self.get_serializer(self._with_creators([template])[0]).data

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        templates = list_templates(self.team_id)
        page = self.paginate_queryset(templates)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(self._with_creators(page), many=True).data)
        return Response(self.get_serializer(self._with_creators(list(templates)), many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self._serialize(self.get_object()))

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = create_template(self.team_id, request.user.id, serializer.validated_data)
        # report_user_action injects source and MCP-client properties from the request, so a create from the
        # visual editor and one from the agent count in the same metric. Capture must never break the request.
        try:
            report_user_action(
                self.request.user,
                "message_template_created",
                {
                    "template_id": str(template.id),
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
        data = self._serialize(template)
        return Response(data, status=status.HTTP_201_CREATED, headers=self.get_success_headers(data))

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        template = self.get_object()
        serializer = self.get_serializer(self._with_creators([template])[0], data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated = update_template(self.team_id, template.id, serializer.validated_data)
        self._emit_resource_edited(updated)
        return Response(self._serialize(updated))

    def _emit_resource_edited(self, instance: MessageTemplateRow) -> None:
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

    @extend_schema(
        request=DesignPatchSerializer, responses={200: MessageTemplateSerializer}, parameters=[TEMPLATE_ID_PARAMETER]
    )
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
        template = self.get_object()

        def apply_operations(content: dict[str, Any]) -> dict[str, Any]:
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
                logger.info("email_template_design_warning", warning=warning, template_id=str(template.id))

            email["design"] = new_design
            # Drop html so the serializer re-renders it from the patched design (its design->html path).
            email.pop("html", None)
            content["email"] = email

            serializer = self.get_serializer(
                self._with_creators([template])[0], data={"content": content}, partial=True
            )
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data["content"]

        locked = edit_template_content(self.team_id, template.id, apply_operations)

        self._emit_resource_edited(locked)
        return Response(self._serialize(locked))
