from collections.abc import Sequence
from dataclasses import fields as dataclass_fields
from types import SimpleNamespace
from typing import Any

from django.db import transaction

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.event_usage import groups, report_user_action
from posthog.models import User
from posthog.models.integration import Integration
from posthog.models.tag import tagify
from posthog.permissions import is_authenticated_via_project_secret_api_key
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.cdp.backend.presentation.hog_functions import build_html_wrap_design
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
    save_template_draft,
    team_category_id,
    update_template,
)
from products.messaging.backend.facade.transactional_email import (
    SENDER_ADDRESS_MAX_LENGTH,
    DeliveryUnavailable,
    TransactionalEmailError,
    check_transactional_update,
    lock_transactional_workflow_id,
    make_transactional,
    send_transactional_email,
    sender_address_error,
    sync_transactional_workflow,
)
from products.messaging.backend.presentation.views.serializers import DesignOperationSerializer
from products.notifications.backend.facade.api import publish_resource_edited
from products.workflows.backend.facade.api import WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.facade.workflows import get_workflow

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


class EmailTemplateSenderSerializer(serializers.Serializer):
    email = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SENDER_ADDRESS_MAX_LENGTH,
        help_text="Address to send from instead of the sender's own. Must be on the sender's verified domain. "
        "Supports Liquid templating. Leave out or empty to use the sender's address.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Sender name shown in the inbox instead of the sender's own. Supports Liquid templating. "
        "Leave out or empty to use the sender's name.",
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        # Keys match the workflow email step, which a transactional template's sender is copied into.
        fields["integrationId"] = serializers.IntegerField(
            help_text="ID of the project's email sender integration that sends this email. Transactional sends "
            "need a verified sender."
        )
        return fields

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        # A partial update doesn't enforce required nested fields, so the sender is checked here.
        integration_id = data.get("integrationId")
        if integration_id is None:
            raise serializers.ValidationError({"integrationId": "Choose an email sender."})
        if not Integration.objects.filter(team_id=self.context["team_id"], kind="email", id=integration_id).exists():
            raise serializers.ValidationError({"integrationId": "No email sender with this ID in this project."})
        return data


def _without_legacy_sender(email: Any, *, reading: bool) -> Any:
    # Only a transactional template stores a sender object. A blank template, a template saved before senders
    # existed, and one saved from a destination's email editor hold a string or an empty object instead.
    if not isinstance(email, dict) or "from" not in email:
        return email
    sender = email["from"]
    # A write that names a sender but no integration is rejected later, so only reads drop it.
    is_legacy = not isinstance(sender, dict) or not (sender.get("integrationId") if reading else any(sender.values()))
    return {key: value for key, value in email.items() if key != "from"} if is_legacy else email


class EmailTemplateSerializer(serializers.Serializer):
    subject = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Email subject line. Supports Liquid templating. Required in `content` for email-type templates. "
        "A `draft_content` may leave it blank until it is published.",
    )
    text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Plain-text fallback body for clients that can't render the email.",
    )
    preheader = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Preview text that most inboxes show after the subject. Supports Liquid templating.",
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

    def to_internal_value(self, data: Any) -> Any:
        return super().to_internal_value(_without_legacy_sender(data, reading=False))

    def to_representation(self, instance: Any) -> Any:
        return super().to_representation(_without_legacy_sender(instance, reading=True))

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["from"] = EmailTemplateSenderSerializer(
            required=False,
            help_text="The sender a transactional template sends from. A template made transactional without "
            "one gets the sender it was made transactional with.",
        )
        fields["replyTo"] = serializers.CharField(
            required=False,
            allow_blank=True,
            help_text="Reply-to address for a transactional template. Separate several addresses with commas. "
            "Supports Liquid templating. Leave empty to use the sender's default reply-to.",
        )
        return fields


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


# Each tag costs get_or_create round trips in set_tags_on_object, so cap the list.
_MAX_TEMPLATE_TAGS = 10
_MAX_TAG_LENGTH = 255  # Tag.name column limit.


class MessageTemplateSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=400, help_text="Human-readable template name shown in the library.")
    description = serializers.CharField(
        allow_blank=True,
        required=False,
        style={"base_template": "textarea.html"},
        help_text="What the template is for and when to use it.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=_MAX_TAG_LENGTH),
        required=False,
        max_length=_MAX_TEMPLATE_TAGS,
        help_text=(
            "Tags for organizing templates, for example by team or use case. Tags are shared with the rest of "
            "the project. Omit to keep the current tags, send an empty list to remove them all."
        ),
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
    sensitive = serializers.BooleanField(
        required=False,
        help_text="For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent "
        "email's body or filled-in subject, and clicked links keep only the site address. Can change at any time.",
    )
    transactional_hog_flow_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="The workflow that sends this template over the transactional email API. Null until the "
        "template is made transactional. Each content save writes a new version of it.",
    )
    draft_content = MessageTemplateContentSerializer(
        required=False,
        allow_null=True,
        help_text="Unpublished edits to a transactional template's content. Sends keep using `content`. Saving "
        "`content` publishes it and clears the draft. Set null to discard the draft.",
    )

    def validate_tags(self, tags: list[str]) -> list[str]:
        # The stored name is the tagified one, and lowercasing can lengthen a string: "\u0130" becomes two
        # code points. Checking the submitted length alone lets an over-long name reach Tag.name.
        if any(len(tagify(tag)) > _MAX_TAG_LENGTH for tag in tags):
            raise serializers.ValidationError(f"A tag may be at most {_MAX_TAG_LENGTH} characters once lowercased.")
        return tags

    def validate(self, data: Any) -> Any:
        template_type = data.get("type")
        email = data.get("content", {}).get("email") if data.get("content") else None
        # Only published content needs a subject. A draft may still be missing one.
        if email and (template_type == "email" or "subject" in email) and not email.get("subject"):
            raise serializers.ValidationError(
                {"content": {"email": {"subject": "Subject is required for email templates."}}}
            )
        # Checked on publish only, so a draft still saves while someone types the address.
        if email and email.get("from") and (error := sender_address_error(self.context["team_id"], email["from"])):
            raise serializers.ValidationError({"content": {"email": {"from": {"email": error}}}})
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

IDEMPOTENCY_KEY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=False,
    description="A unique key for this email, 1 to 255 visible ASCII characters. Retrying with the same key and "
    "the same request within 24 hours sends nothing new and returns the first send's `message_id`. Reusing a key "
    "for a different request returns a 422.",
)


TRANSACTIONAL_EMAIL_API_FLAG = "workflows-transactional-email-api"


class TransactionalEmailIdentifiersSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=400,
        help_text="Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, "
        "clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email "
        "address. The template can't read the person's properties, so pass everything it needs in `message_data`.",
    )


class SendTransactionalEmailSerializer(serializers.Serializer):
    to = serializers.EmailField(help_text="Email address of the recipient.")
    identifiers = TransactionalEmailIdentifiersSerializer(
        required=False, help_text="Who the email is for, used to attribute engagement events."
    )
    message_data = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        default=dict,
        help_text="Data for the template's Liquid placeholders, available as `variables`. "
        'For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.',
    )


class MakeTransactionalSerializer(serializers.Serializer):
    from_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the verified email sender integration the email is sent from. Defaults to the project's "
        "default sender.",
    )


class SendTransactionalEmailResponseSerializer(serializers.Serializer):
    message_id = serializers.CharField(
        help_text="ID of the queued send. Delivery and engagement are reported against the template asynchronously."
    )
    replayed = serializers.BooleanField(
        help_text="True when an earlier request with the same `Idempotency-Key` already queued this email. "
        "No new email was sent, and `message_id` is the earlier send's ID."
    )


class TransactionalEmailRejected(exceptions.APIException):
    STATUS_BY_CODE = {"quota_limited": 429, "idempotency_key_in_flight": 409, "idempotency_key_reused": 422}
    # The caller has to change the request. Without this the error handler reports a server error.
    default_type = "invalid_request"

    def __init__(self, error: TransactionalEmailError) -> None:
        self.status_code = self.STATUS_BY_CODE.get(error.code, status.HTTP_400_BAD_REQUEST)
        super().__init__(detail=str(error), code=error.code)


class TransactionalEmailUnavailable(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The email pipeline is unavailable. Try again shortly."
    default_code = "delivery_unavailable"


class TransactionalEmailBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_burst"
    rate = "600/minute"


class TransactionalEmailSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_sustained"
    rate = "20000/hour"


class TransactionalEmailTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate across all of a project's secret API keys."""

    scope = "transactional_email_psak_team_burst"
    rate = "600/minute"


class TransactionalEmailTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_psak_team_sustained"
    rate = "20000/hour"


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
    # `design` and `send` are custom write actions; list them so programmatic callers (MCP/personal API key)
    # get hog_flow:write checked instead of being rejected as an action with no declared scope.
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "design",
        "send",
        "make_transactional",
    ]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    # A project secret API key can only send. Template CRUD stays session/personal API key/OAuth only.
    psak_allowed_actions = ["send"]

    serializer_class = MessageTemplateSerializer

    def get_throttles(self):
        if self.action == "send":
            return [
                TransactionalEmailBurstThrottle(),
                TransactionalEmailSustainedThrottle(),
                TransactionalEmailTeamBurstThrottle(),
                TransactionalEmailTeamSustainedThrottle(),
            ]
        return super().get_throttles()

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
        fields = serializer.validated_data
        if fields.keys() == {"draft_content"}:
            # Sends never read the draft, so it skips the sendability check and the workflow sync. It is still an edit
            # of the transactional email, so it needs the same workflow access as a publish.
            if template.transactional_hog_flow_id:
                self._require_workflow_editor(template.transactional_hog_flow_id)
            updated = save_template_draft(self.team_id, template.id, fields["draft_content"])
            self._emit_resource_edited(updated)
            return Response(self._serialize(updated))
        if fields.keys() == {"tags"}:
            # Tags are library metadata. Sends never read them, so a tag edit skips the sendability check
            # and must not write a new version of the template's transactional workflow.
            updated = update_template(self.team_id, template.id, fields)
            self._emit_resource_edited(updated)
            return Response(self._serialize(updated))
        if "content" in fields:
            fields["draft_content"] = None
        # Sends use the workflow's copy, so the template and its new workflow version are saved together,
        # under a row lock that keeps a concurrent make_transactional from slipping in between.
        with transaction.atomic():
            hog_flow_id = lock_transactional_workflow_id(self.team_id, template.id)
            if hog_flow_id:
                self._require_workflow_editor(hog_flow_id)
                try:
                    check_transactional_update(template.id, self.team_id, fields)
                except TransactionalEmailError as e:
                    raise TransactionalEmailRejected(e) from None
            updated = update_template(self.team_id, template.id, fields)
            if hog_flow_id and not updated.deleted:
                self._sync_transactional_workflow(template.id)
                # The sync unlinks the template when its workflow was deleted.
                updated = get_template(self.team_id, template.id)
        self._emit_resource_edited(updated)
        return Response(self._serialize(updated))

    def _sync_transactional_workflow(self, template_id: Any) -> None:
        # Raising rolls back the template save, so the template and its workflow never disagree.
        try:
            sync_transactional_workflow(self.team_id, template_id, user_id=self._actor_id())
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None

    def _require_workflow_editor(self, hog_flow_id: Any) -> None:
        # The template's own access rules don't cover the workflow it sends through, which can carry its own.
        # A project secret API key has no user to check, and its scope already limits it to sending.
        if is_authenticated_via_project_secret_api_key(self.request):
            return
        try:
            get_workflow(
                team_id=self.team_id,
                workflow_id=str(hog_flow_id),
                user_access_control=self.user_access_control,
                required_level="editor",
            )
        except WorkflowAccessDenied:
            raise exceptions.PermissionDenied(
                "You need editor access to this template's transactional email workflow."
            ) from None
        except WorkflowNotFound:
            return

    def _actor_id(self) -> int | None:
        return self.request.user.id if self.request.user.is_authenticated else None

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

        with transaction.atomic():
            # Checked under the row lock, so a template made transactional meanwhile is checked too.
            hog_flow_id = lock_transactional_workflow_id(self.team_id, template.id)
            if hog_flow_id:
                self._require_workflow_editor(hog_flow_id)
            locked = edit_template_content(self.team_id, template.id, apply_operations)
            if hog_flow_id:
                self._sync_transactional_workflow(template.id)
                # The sync unlinks the template when its workflow was deleted.
                locked = get_template(self.team_id, template.id)

        self._emit_resource_edited(locked)
        return Response(self._serialize(locked))

    @validated_request(
        SendTransactionalEmailSerializer,
        responses={
            202: OpenApiResponse(response=SendTransactionalEmailResponseSerializer, description="Email queued"),
            400: OpenApiResponse(
                description="The template isn't transactional or its email is paused, the recipient can't be used, "
                "or the Idempotency-Key is invalid"
            ),
            404: OpenApiResponse(description="Template not found"),
            409: OpenApiResponse(description="A request with the same Idempotency-Key is still in progress"),
            422: OpenApiResponse(description="The Idempotency-Key was already used for a different request"),
            429: OpenApiResponse(description="Rate limited, or the project is over its email quota"),
            503: OpenApiResponse(description="The email pipeline did not confirm the send"),
        },
        summary="Send a transactional email",
        description=(
            "Send one transactional email from this template to one recipient. The template must be made "
            "transactional first. `message_data` fills the template's `{{ variables.* }}` placeholders. "
            "Transactional emails skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry "
            "safely without sending the email twice."
        ),
        parameters=[TEMPLATE_ID_PARAMETER, IDEMPOTENCY_KEY_PARAMETER],
    )
    @action(detail=True, methods=["POST"], pagination_class=None)
    def send(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()

        template = self.get_object()
        if template.transactional_hog_flow_id:
            self._require_workflow_editor(template.transactional_hog_flow_id)
        data = request.validated_data
        idempotency_key = request.headers.get("Idempotency-Key")
        outcome: dict[str, Any] = {"outcome": "error", "has_idempotency_key": idempotency_key is not None}
        try:
            queued = send_transactional_email(
                self.team,
                template.id,
                to=data["to"],
                distinct_id=(data.get("identifiers") or {}).get("distinct_id") or None,
                message_data=data["message_data"],
                idempotency_key=idempotency_key,
            )
            outcome["outcome"] = "replayed" if queued.replayed else "queued"
        except TransactionalEmailError as e:
            outcome.update({"outcome": "rejected", "error_code": e.code})
            raise TransactionalEmailRejected(e)
        except DeliveryUnavailable:
            outcome["outcome"] = "unavailable"
            raise TransactionalEmailUnavailable() from None
        finally:
            self._report_transactional_email_send(request, template, outcome)
        return Response(
            SendTransactionalEmailResponseSerializer(queued).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def _require_transactional_email_flag(self) -> None:
        if not posthoganalytics.feature_enabled(
            TRANSACTIONAL_EMAIL_API_FLAG,
            str(self.team.uuid),
            groups={"organization": str(self.team.organization_id)},
            group_properties={"organization": {"id": str(self.team.organization_id)}},
            send_feature_flag_events=False,
        ):
            raise NotFound()

    @validated_request(
        MakeTransactionalSerializer,
        responses={
            200: OpenApiResponse(response=MessageTemplateSerializer, description="The transactional template"),
            400: OpenApiResponse(description="The template can't be sent, or there is no verified sender"),
            404: OpenApiResponse(description="Template not found"),
        },
        summary="Make a template transactional",
        description=(
            "Make this template sendable over the transactional email API. This creates the workflow that sends it, "
            "with its own metrics, run history and versions. This can't be undone: the template stays transactional. "
            "Transactional sends ignore marketing opt-outs. Calling it again on a transactional template changes "
            "nothing."
        ),
        parameters=[TEMPLATE_ID_PARAMETER],
    )
    @action(detail=True, methods=["POST"], pagination_class=None)
    def make_transactional(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()
        template = self.get_object()
        was_transactional = template.transactional_hog_flow_id is not None
        # Access to one workflow lets a member through the viewset's checks, but this can create a new one, also
        # when the linked workflow was deleted.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise exceptions.PermissionDenied("You need editor access to workflows to make a template transactional.")
        try:
            make_transactional(
                self.team_id,
                template.id,
                user_id=self._actor_id(),
                from_integration_id=request.validated_data.get("from_integration_id"),
            )
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None
        updated = self.get_object()
        if not was_transactional:
            self._emit_resource_edited(updated)
            try:
                report_user_action(
                    self.request.user,
                    "message template made transactional",
                    {"template_id": str(template.id), "team_id": str(self.team_id)},
                    team=self.team,
                    organization=self.organization,
                    request=self.request,
                )
            except Exception as e:
                logger.warning("Failed to capture message template usage event", error=str(e))
        return Response(self._serialize(updated))

    def _report_transactional_email_send(
        self, request: Any, template: MessageTemplateRow, outcome: dict[str, Any]
    ) -> None:
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly.
        try:
            posthoganalytics.capture(
                distinct_id=request.user.distinct_id,
                event="transactional email api send",
                properties={
                    "template_id": str(template.id),
                    "team_id": self.team_id,
                    "auth_method": "project_secret_api_key"
                    if is_authenticated_via_project_secret_api_key(request)
                    else "user",
                    **outcome,
                },
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email usage event", error=str(e))
