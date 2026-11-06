import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import fields as dataclass_fields
from email.utils import parseaddr
from types import SimpleNamespace
from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
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
from rest_framework import exceptions, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import ResponseDeclaration, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import ProjectSecretAPIKeyAuthentication, ProjectSecretAPIKeyUser
from posthog.event_usage import groups, report_user_action
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import ProjectSecretAPIKey, User
from posthog.models.tag import tagify
from posthog.permissions import (
    is_authenticated_via_project_secret_api_key,
    legacy_scope_object_used,
    scopes_caller_lacks,
)
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.cdp.backend.presentation.hog_functions import build_html_wrap_design, html_wrap_design_needs_refresh
from products.messaging.backend.facade.api import (
    UnlayerNotConfiguredError,
    UnlayerRenderError,
    apply_design_operations,
    render_design_html,
    validate_design,
)
from products.messaging.backend.facade.contracts import (
    TEMPLATE_KEY_MAX_LENGTH,
    ContentHashState,
    TemplateEditedInPostHog,
    TemplateManagedBy,
    TemplateManagedByCode,
    TemplateReleasedTo,
    TemplateSource,
    TemplateUpload,
    TemplateUploadResult,
    TemplateWriteIntent,
    TemplateWriteRefused,
)
from products.messaging.backend.facade.templates import (
    MessageCategoryNotInTeam,
    MessageTemplateMissing,
    MessageTemplateRow,
    UploadedTemplate,
    adopt_template,
    check_template_key_write,
    check_template_write,
    create_template,
    find_template_to_send,
    get_template,
    is_adoption,
    is_release,
    list_templates,
    release_template,
    save_template_content,
    save_template_draft,
    save_template_fields,
    save_template_tags,
    team_category_id,
    upload_template,
)
from products.messaging.backend.facade.transactional_email import (
    SENDER_ADDRESS_MAX_LENGTH,
    SENDER_ADDRESS_PATTERN,
    CodeEmail,
    DeliveryUnavailable,
    EmailAttachment,
    FieldNotAccepted,
    QueuedEmail,
    TemplateOutdated,
    TemplateSendOptions,
    TransactionalEmailError,
    TransactionalEmailStage,
    WorkflowVersionBehind,
    make_transactional,
    observe_transactional_email_stage,
    report_first_code_send,
    require_code_email_access,
    send_code_email,
    send_transactional_email,
    sender_address_error,
    transactional_email_stage,
)
from products.messaging.backend.presentation.views.code_send_fields import (
    CODE_SEND_EXTRA_FIELDS,
    AddressListField,
    AttachmentListField,
    field_not_accepted_refusal,
    template_send_refusal,
    uploaded_template_send_refusal,
    validate_pipeline_address,
    with_code_send_reason,
)
from products.messaging.backend.presentation.views.serializers import DesignOperationSerializer
from products.messaging.backend.presentation.views.template_refusals import (
    TemplateErrorSerializer,
    TemplateRefusal,
    invalid_request,
    invalid_template_key,
    template_edited_in_posthog,
)
from products.notifications.backend.facade.api import publish_resource_edited
from products.workflows.backend.facade.api import WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.facade.transactional_emails import EMAIL_FROM_CODE_FLAG
from products.workflows.backend.facade.workflows import get_workflow

logger = structlog.get_logger(__name__)


# Shallow skeleton of the Unlayer design document — enough structure for API callers
# (and the LLMs behind MCP tools) to author against; the full row/column/content
# shape is documented in the designing-email-templates skill.
@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "counters": {
                "type": "object",
                "description": 'Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}.',
            },
            "schemaVersion": {"type": "integer", "description": "Design schema version, e.g. 16."},
            "body": {
                "type": "object",
                "additionalProperties": True,
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
        try:
            IntegrationManager.email.credentials.get(self.context["team_id"], integration_id)
        except IntegrationNotFound:
            raise serializers.ValidationError(
                {"integrationId": "No email sender with this ID in this project."}
            ) from None
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
    key = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Stable identifier code uses to upload and send this template, unique within the project. Null "
        "for templates that have no key. Set once, by the first upload or by a PATCH whose only field is `key`.",
    )
    managed_by = serializers.ChoiceField(
        choices=TemplateManagedBy.choices,
        read_only=True,
        allow_null=True,
        help_text="Who owns the content. `code` when it was uploaded from a repository: PostHog then refuses edits, and "
        "the template changes through its next upload. To edit it in PostHog, send a PATCH whose only field is "
        "`managed_by` set to `gui`. `gui` or null when it is edited in PostHog.",
    )
    source_repository = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Repository the template was last uploaded from, such as `github.com/example/app`.",
    )
    source_path = serializers.CharField(
        read_only=True, allow_null=True, help_text="Path of the template file in the source repository."
    )
    source_ref = serializers.CharField(
        read_only=True, allow_null=True, help_text="Commit or branch the template was last uploaded from."
    )
    content_hash = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters. Changes "
        "with every save that changes them.",
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
        if email and email.get("html") and html_wrap_design_needs_refresh(email["html"], email.get("design")):
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


class MessageTemplateUpdateSerializer(MessageTemplateSerializer):
    key = serializers.CharField(
        required=False,
        max_length=TEMPLATE_KEY_MAX_LENGTH,
        help_text="Give a template that has no key one, so code can take it over: the next upload under this key "
        "updates this template and keeps its id, workflow and sender. Code sends that already use this key keep "
        "their own workflow until that upload, then run through this template's workflow. Send it as the only field "
        "of the PATCH. Letters, digits, hyphens (-) and underscores (_). Set once: a template that has a key keeps it.",
    )
    managed_by = serializers.ChoiceField(
        choices=TemplateReleasedTo.choices,
        required=False,
        help_text="Send `gui` as the only field to stop managing a template in code, so it can be edited in PostHog. "
        "It keeps its key, so the next upload under that key manages it in code again.",
    )


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
FIRST_CODE_SEND_EVENT = "email first code send"


DISTINCT_ID_HELP_TEXT = (
    "Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, clicked, "
    "bounced) and the send itself are recorded against that person. Defaults to the recipient's email address. "
    "The template can't read the person's properties, so pass everything it needs in `message_data`."
)


class TransactionalEmailIdentifiersSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=400, help_text=DISTINCT_ID_HELP_TEXT
    )


class TransactionalEmailMessageSerializer(serializers.Serializer):
    to = serializers.EmailField(validators=[validate_pipeline_address], help_text="Email address of the recipient.")
    message_data = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        default=dict,
        help_text="Data for the template's Liquid placeholders, available as `variables`. "
        'For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.',
    )


class SendTransactionalEmailSerializer(TransactionalEmailMessageSerializer):
    identifiers = TransactionalEmailIdentifiersSerializer(
        required=False, help_text="Who the email is for, used to attribute engagement events."
    )


def refuse_unknown_fields(sent: Iterable[str], known: Mapping[str, Any]) -> None:
    unknown = next((field for field in sorted(sent) if field not in known), None)
    if unknown is not None:
        raise serializers.ValidationError(
            {unknown: "PostHog doesn't take this field, so it doesn't send the email without it."}
        )


RENDERED_CONTENT_FIELDS = ("subject", "html", "text")
TEMPLATE_ID_REFUSED_FIELDS = ("template_hash", *RENDERED_CONTENT_FIELDS, "from", "reply_to")
CODE_BODY_MAX_BYTES = 5 * 1024 * 1024
TEMPLATE_HASH_REFUSAL = (
    "Only a send of an uploaded template takes this field: `template_key` without `subject`, `html` or `text`."
)


def sends_uploaded_template(data: Mapping[str, Any]) -> bool:
    return "template_key" in data and not any(field in data for field in RENDERED_CONTENT_FIELDS)


class SendEmailSerializer(TransactionalEmailMessageSerializer):
    template_id = serializers.UUIDField(
        required=False,
        help_text="ID of the email template to send. The template must be made transactional first. Send either "
        "`template_id` or `template_key`.",
    )
    template_key = serializers.RegexField(
        r"^[a-zA-Z0-9_-]+$",
        max_length=TEMPLATE_KEY_MAX_LENGTH,
        required=False,
        help_text="Key of the email, such as `order-shipped`, so its metrics, logs and status group under it. "
        "Letters, numbers, hyphens (-) and underscores (_) only. Send it with `subject` and `html` or `text` to "
        "send content your code rendered: PostHog sends the content as is and never stores it as a template. Send "
        "it without them to send the template uploaded under this key with `PUT "
        "/api/projects/@current/messaging_templates/by_key/{key}/`, with `message_data` filling its placeholders. "
        "Once you upload a template under a key, sends of rendered content with that key also run through the "
        "template's workflow, so their metrics and logs group with the template.",
    )
    template_hash = serializers.RegexField(
        r"^v1:[0-9a-f]{64}$",
        required=False,
        error_messages={
            "invalid": "Send the hash as `v1:` and 64 lowercase hex characters, as an upload's `content_hash`."
        },
        help_text="Content hash of the uploaded template you hold, as an upload's `content_hash`. When PostHog "
        "doesn't hold that content as the current content or one of the last 100 contents it replaced, the send "
        "answers `409 template_outdated` and sends nothing. Only with `template_key` and no `subject`, `html` or "
        "`text`.",
    )
    distinct_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=400, help_text=DISTINCT_ID_HELP_TEXT
    )
    subject = serializers.CharField(
        required=False, trim_whitespace=False, help_text="Subject of the email your code rendered."
    )
    html = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="HTML body of the email your code rendered, at most 5 MiB as UTF-8.",
    )
    text = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Plain text body of the email your code rendered, at most 5 MiB as UTF-8. Without it, PostHog "
        "derives the text from `html`.",
    )
    from_address = serializers.CharField(
        required=False,
        # parseaddr() is quadratic on group addresses, so the raw value is bounded before validate_from parses it.
        max_length=1024,
        help_text="Sender of the email, as `security@example.com` or `Example <security@example.com>`, on a verified "
        "domain of the project. Without it, an email your code rendered goes out from the project's default sender, "
        "or from its only verified sender when it has no default, and an uploaded template from its own sender. A "
        "send with `template_id` doesn't take it.",
    )
    reply_to = serializers.ListField(
        child=serializers.EmailField(validators=[validate_pipeline_address]),
        required=False,
        allow_empty=False,
        max_length=10,
        help_text="Addresses replies to the email go to. A send with `template_id` doesn't take it.",
    )
    cc = AddressListField(
        required=False,
        allow_null=True,
        help_text="Addresses that get a visible copy of the email your code rendered: one address, or a list of up "
        "to 10. Each is a bare address such as `jane@example.com`, with no name. Doesn't apply to a send of a "
        "template, which refuses any address here.",
    )
    bcc = AddressListField(
        required=False,
        allow_null=True,
        help_text="Addresses that get a hidden copy of the email your code rendered: one address, or a list of up "
        "to 10. Each is a bare address such as `jane@example.com`, with no name. Doesn't apply to a send of a "
        "template, which refuses any address here.",
    )
    attachments = AttachmentListField(
        required=False,
        allow_null=True,
        help_text="Files attached to the email your code rendered: up to 10, and at most 512 KB in total after "
        "decoding. File types mailbox providers block, such as `.exe`, are refused. Doesn't apply to a send of a "
        "template, which refuses any file here.",
    )
    capture_engagement = serializers.BooleanField(
        required=False,
        help_text="Whether the engagement events (sent, delivered, opened, clicked, bounced) of the email are "
        "captured as analytics events of the recipient. Defaults to true. A project whose admin turned engagement "
        "capture off captures nothing, whatever the send says. A send with `template_id` takes it only in the beta "
        "for sending email from code.",
    )

    def to_internal_value(self, data: Any) -> Any:
        # posthog-node 5.61.0 and posthog 7.81.0 send `template.id` and `identifiers.distinct_id`, so that shape
        # stays accepted. It is left out of the schema so that new callers use the flat fields.
        if isinstance(data, Mapping):
            template, identifiers = data.get("template"), data.get("identifiers")
            if "template_id" not in data and isinstance(template, Mapping):
                data = {**data, "template_id": template.get("id")}
            if "distinct_id" not in data and isinstance(identifiers, Mapping):
                data = {**data, "distinct_id": identifiers.get("distinct_id")}
        return super().to_internal_value(data)

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["from"] = fields.pop("from_address")
        return fields

    def validate_html(self, value: str) -> str:
        return _within_body_limit(value, "The HTML body")

    def validate_text(self, value: str) -> str:
        return _within_body_limit(value, "The plain text body")

    def validate_from(self, value: str) -> str:
        try:
            _name, address = parseaddr(value)
        except RecursionError:
            address = ""
        if not _is_sender_address(address):
            raise serializers.ValidationError("Enter an address, such as `Example <security@example.com>`.")
        return value

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        sent = set(self.initial_data) if isinstance(self.initial_data, Mapping) else set()
        if ("template_id" in data) == ("template_key" in data):
            raise serializers.ValidationError({"template_id": "Send either `template_id` or `template_key`."})
        if "template_id" in data:
            return self._validate_template_id_send(data, sent)
        refuse_unknown_fields(sent, self.fields)
        if sends_uploaded_template(sent):
            return self._validate_uploaded_template_send(data)
        if "template_hash" in sent:
            raise serializers.ValidationError({"template_hash": TEMPLATE_HASH_REFUSAL})
        if "message_data" in sent:
            raise serializers.ValidationError(
                {"message_data": "A send with `template_key` carries content your code rendered, not `message_data`."}
            )
        if not data.get("subject"):
            raise serializers.ValidationError({"subject": "A send with `template_key` needs a subject."})
        if not (data.get("html") or data.get("text")):
            raise serializers.ValidationError({"html": "A send with `template_key` needs `html`, `text` or both."})
        return data

    @staticmethod
    def _validate_template_id_send(data: dict[str, Any], sent: set[str]) -> dict[str, Any]:
        _drop_empty_extra_fields(data, template_send_refusal)
        if field := next((field for field in TEMPLATE_ID_REFUSED_FIELDS if field in sent), None):
            raise serializers.ValidationError({field: _refusal_on_a_template_id_send(field)})
        return data

    @staticmethod
    def _validate_uploaded_template_send(data: dict[str, Any]) -> dict[str, Any]:
        _drop_empty_extra_fields(data, uploaded_template_send_refusal)
        return data


def _drop_empty_extra_fields(data: dict[str, Any], refusal: Callable[[str], serializers.ValidationError]) -> None:
    if extra_field := next((field for field in CODE_SEND_EXTRA_FIELDS if data.get(field)), None):
        raise refusal(extra_field)
    for field in CODE_SEND_EXTRA_FIELDS:
        data.pop(field, None)


def _refusal_on_a_template_id_send(field: str) -> str:
    if field == "template_hash":
        return TEMPLATE_HASH_REFUSAL
    if field in ("from", "reply_to"):
        return (
            "A template made in PostHog sends with its own settings. Send with `template_key` to set this field on a "
            "template uploaded from code."
        )
    return "Only a send with `template_key` takes this field."


def _within_body_limit(value: str, body: str) -> str:
    if len(value.encode()) > CODE_BODY_MAX_BYTES:
        raise serializers.ValidationError(
            f"{body} can be at most 5 MiB as UTF-8. Link to large images and files instead of embedding them."
        )
    return value


def _is_sender_address(address: str) -> bool:
    if len(address) > SENDER_ADDRESS_MAX_LENGTH or not SENDER_ADDRESS_PATTERN.match(address):
        return False
    try:
        validate_email(address)
    except DjangoValidationError:
        return False
    return True


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


class SendEmailWarningSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable code of the warning, such as `template_superseded`.")
    detail = serializers.CharField(help_text="What happened.")
    fix = serializers.CharField(help_text="What you can change, if the warning isn't what you want.")


class SendEmailResponseSerializer(SendTransactionalEmailResponseSerializer):
    warnings = SendEmailWarningSerializer(
        many=True, required=False, help_text="Things to know about the queued email. Left out when there are none."
    )


TEMPLATE_SUPERSEDED_WARNING = {
    "code": "template_superseded",
    "detail": "The email went out with the template's current content, because newer content replaced the content "
    "you hold.",
    "fix": "Deploy the newer file, or upload yours to publish it again.",
}


class TemplateKeyNotFound(exceptions.NotFound):
    default_detail = "No template in this project has this key, so nothing was sent. Upload the template, then send "
    "again."
    default_code = "template_not_found"


class TransactionalEmailRejected(exceptions.ValidationError):
    STATUS_BY_CODE = {
        "template_outdated": 409,
        "quota_limited": 429,
        "idempotency_key_in_flight": 409,
        "idempotency_key_reused": 422,
        "sending_suspended": 422,
        "sending_paused": 422,
        "recipient_suppressed": 422,
        "recipient_unreachable": 422,
    }
    # The caller has to change the request. Without this the error handler types it `validation_error`.
    default_type = "invalid_request"

    def __init__(self, error: TransactionalEmailError) -> None:
        self.status_code = self.STATUS_BY_CODE.get(error.code, status.HTTP_400_BAD_REQUEST)
        super().__init__(detail={error.attr: [str(error)]} if error.attr else str(error), code=error.code)


class TransactionalEmailUnavailable(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The email pipeline is unavailable. Try again shortly."
    default_code = "delivery_unavailable"


class PipelineHoldsAnOlderWorkflow(TransactionalEmailUnavailable):
    default_detail = (
        "This template's newest version hasn't reached the email pipeline yet, so nothing was sent. Retry in a few "
        "seconds, with the same Idempotency-Key if you sent one."
    )


class UnconfirmedEmailSend(TransactionalEmailUnavailable):
    default_detail = (
        "The email pipeline did not confirm the send, so the email may still go out. To retry, send it again "
        "within 24 hours with the same Idempotency-Key, so it goes out once. A retry without that key, or after "
        "that time, may send it twice."
    )


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


# LEGACY_SCOPE_FALLBACKS lets a `hog_flow` key satisfy these scopes too.
TRANSACTIONAL_EMAIL_SEND_SCOPE = "transactional_email:write"
TRANSACTIONAL_EMAIL_STATUS_SCOPE = "transactional_email:read"


def transactional_email_authorized_by(request: Any, required_scope: str) -> str:
    return legacy_scope_object_used(request, required_scope) or "transactional_email"


def require_transactional_email_api(team: Any) -> None:
    _require_flag(team, TRANSACTIONAL_EMAIL_API_FLAG)


def require_email_from_code(team: Any) -> None:
    _require_flag(team, EMAIL_FROM_CODE_FLAG)


def require_email_status_read(team: Any) -> None:
    if not (_flag_enabled(team, TRANSACTIONAL_EMAIL_API_FLAG) or _flag_enabled(team, EMAIL_FROM_CODE_FLAG)):
        raise NotFound()


def _require_flag(team: Any, flag: str) -> None:
    if not _flag_enabled(team, flag):
        raise NotFound()


def _flag_enabled(team: Any, flag: str) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            flag,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
    )


class TemplateUploadBurstThrottle(TransactionalEmailBurstThrottle):
    scope = "transactional_email_upload_burst"


class TemplateUploadSustainedThrottle(TransactionalEmailSustainedThrottle):
    scope = "transactional_email_upload_sustained"


class TemplateUploadTeamBurstThrottle(TransactionalEmailTeamBurstThrottle):
    scope = "transactional_email_upload_psak_team_burst"


class TemplateUploadTeamSustainedThrottle(TransactionalEmailTeamSustainedThrottle):
    scope = "transactional_email_upload_psak_team_sustained"


def template_upload_throttles() -> list[BaseThrottle]:
    return [
        TemplateUploadBurstThrottle(),
        TemplateUploadSustainedThrottle(),
        TemplateUploadTeamBurstThrottle(),
        TemplateUploadTeamSustainedThrottle(),
    ]


def transactional_email_throttles() -> list[BaseThrottle]:
    # Both send routes share these scopes, so a caller can't double its rate by using both.
    return [
        TransactionalEmailBurstThrottle(),
        TransactionalEmailSustainedThrottle(),
        TransactionalEmailTeamBurstThrottle(),
        TransactionalEmailTeamSustainedThrottle(),
    ]


SEND_RESPONSES: dict[int, ResponseDeclaration] = {
    202: OpenApiResponse(response=SendTransactionalEmailResponseSerializer, description="Email queued"),
    400: OpenApiResponse(
        description="A field is invalid, the template isn't transactional or its email is paused, the sender isn't "
        "verified, the recipient can't be used, the Idempotency-Key is invalid, the email is too large to send, or "
        "the project has reached its limit of template keys and the `template_key` is new"
    ),
    404: OpenApiResponse(description="Template not found"),
    409: OpenApiResponse(
        description="A request with the same Idempotency-Key is still in progress, or PostHog doesn't hold the "
        "content `template_hash` describes"
    ),
    422: OpenApiResponse(
        description="The email can't go out: the recipient is suppressed or can't receive email, sending is "
        "suspended for the project or paused for this transactional email, or the Idempotency-Key was already "
        "used for a different request"
    ),
    429: OpenApiResponse(description="Rate limited, or the project is over its email quota"),
    503: OpenApiResponse(description="The email pipeline did not confirm the send"),
}


# The send path shared by the template-scoped route and the single send route. A comment, not a docstring:
# drf-spectacular would publish a docstring as the description of every operation on both viewsets.
class TransactionalEmailSendMixin:
    request: Any
    team: Any
    team_id: int
    organization: Any
    user_access_control: Any
    # The actions of the viewset that send an email. Only these record stage durations.
    transactional_email_send_actions: tuple[str, ...] = ()
    _validation_started_at: float | None = None

    def _is_transactional_email_send(self) -> bool:
        return getattr(self, "action", None) in self.transactional_email_send_actions

    def _send_stage(self, stage: TransactionalEmailStage) -> AbstractContextManager[None]:
        return transactional_email_stage(stage) if self._is_transactional_email_send() else nullcontext()

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        started_at = time.monotonic()
        try:
            return cast(Any, super()).dispatch(request, *args, **kwargs)
        finally:
            # A body that fails validation never reaches the action, so its validation time is recorded here.
            self._end_request_validation()
            if self._is_transactional_email_send():
                observe_transactional_email_stage("total", time.monotonic() - started_at)

    def perform_authentication(self, request: Any) -> None:
        with self._send_stage("auth"):
            cast(Any, super()).perform_authentication(request)

    def check_permissions(self, request: Any) -> None:
        with self._send_stage("permissions"):
            cast(Any, super()).check_permissions(request)

    def check_throttles(self, request: Any) -> None:
        with self._send_stage("throttle"):
            cast(Any, super()).check_throttles(request)

    def initial(self, request: Any, *args: Any, **kwargs: Any) -> None:
        cast(Any, super()).initial(request, *args, **kwargs)
        # @validated_request parses and validates the body after initial() returns and before the action body runs.
        self._validation_started_at = time.monotonic()

    def _end_request_validation(self) -> None:
        if self._validation_started_at is not None and self._is_transactional_email_send():
            observe_transactional_email_stage("validation", time.monotonic() - self._validation_started_at)
        self._validation_started_at = None

    def _require_transactional_email_flag(self) -> None:
        require_transactional_email_api(self.team)

    def _queue_transactional_email(
        self, request: Any, template: MessageTemplateRow, *, route: str, options: TemplateSendOptions | None = None
    ) -> Response:
        with transactional_email_stage("workflow_access"):
            if template.transactional_hog_flow_id:
                self._require_workflow_editor(template.transactional_hog_flow_id)
        data = request.validated_data
        return self._queue_send(
            request,
            lambda idempotency_key: send_transactional_email(
                self.team,
                template,
                to=data["to"],
                distinct_id=_distinct_id(data),
                message_data=data["message_data"],
                idempotency_key=idempotency_key,
                options=options,
            ),
            route=route,
            addressed={"template_id": str(template.id)},
        )

    def _queue_send(
        self,
        request: Any,
        send: Callable[[str | None], QueuedEmail],
        *,
        route: str,
        addressed: dict[str, str],
        unavailable: type[TransactionalEmailUnavailable] = TransactionalEmailUnavailable,
        warnings: Sequence[dict[str, str]] = (),
    ) -> Response:
        idempotency_key = request.headers.get("Idempotency-Key")
        outcome: dict[str, Any] = {
            "outcome": "error",
            "has_idempotency_key": idempotency_key is not None,
            "route": route,
        }
        try:
            queued = send(idempotency_key)
            outcome["outcome"] = "replayed" if queued.replayed else "queued"
        except FieldNotAccepted as e:
            outcome.update({"outcome": "rejected", "error_code": e.code})
            raise field_not_accepted_refusal(e.field) from None
        except TransactionalEmailError as e:
            outcome.update({"outcome": "rejected", "error_code": e.code})
            raise TransactionalEmailRejected(e)
        except WorkflowVersionBehind:
            outcome["outcome"] = "unavailable"
            raise PipelineHoldsAnOlderWorkflow() from None
        except DeliveryUnavailable:
            outcome["outcome"] = "unavailable"
            raise unavailable() from None
        finally:
            with transactional_email_stage("usage_event"):
                self._report_transactional_email_send(request, {**addressed, **outcome})
        if not queued.replayed:
            self._report_first_code_send_after_commit(request, route, addressed.get("addressed_by", "template_id"))
        data = SendTransactionalEmailResponseSerializer(queued).data
        return Response({**data, "warnings": list(warnings)} if warnings else data, status=status.HTTP_202_ACCEPTED)

    def _require_workflow_editor(self, hog_flow_id: Any) -> None:
        # The template's own access rules don't cover the workflow it sends through, which can carry its own.
        # A project secret API key has no user to check. Its scope limits it to sending and to setting recipient
        # topic preferences.
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

    def _require_workflow_create(self) -> None:
        if is_authenticated_via_project_secret_api_key(self.request):
            return
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise exceptions.PermissionDenied("You need editor access to workflows to send under a new key.")

    def _report_first_code_send_after_commit(self, request: Any, route: str, addressed_by: str) -> None:
        if route != "send_email" or not isinstance(request.user, ProjectSecretAPIKeyUser):
            return
        key = request.user.project_secret_api_key
        if key.created_by_id is None:
            return
        # A code send passed this flag before it went out, so only a send by template id checks it here.
        if addressed_by != "template_key" and not _flag_enabled(self.team, EMAIL_FROM_CODE_FLAG):
            return
        transaction.on_commit(lambda: self._report_first_code_send(key, addressed_by))

    def _report_first_code_send(self, key: ProjectSecretAPIKey, addressed_by: str) -> None:
        try:
            report_first_code_send(self.team_id, lambda: self._capture_first_code_send(key, addressed_by))
        except Exception as e:
            logger.warning("Failed to capture the first code send", team_id=self.team_id, error=str(e))

    def _capture_first_code_send(self, key: ProjectSecretAPIKey, addressed_by: str) -> bool:
        key_creator = User.objects.filter(created_project_secret_api_keys__id=key.pk).first()
        if key_creator is None:
            return False
        # A key made in an environment sends for its project, and the project holds the claim.
        project = self.team.parent_team or self.team
        queued = posthoganalytics.capture(
            distinct_id=key_creator.distinct_id,
            event=FIRST_CODE_SEND_EVENT,
            properties={"team_id": project.id, "addressed_by": addressed_by},
            groups=groups(self.organization, project),
        )
        return queued is not None

    def _report_transactional_email_send(self, request: Any, properties: dict[str, Any]) -> None:
        self._capture_api_usage(request, "transactional email api send", properties)

    def _capture_api_usage(self, request: Any, event: str, properties: dict[str, Any]) -> None:
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly.
        try:
            posthoganalytics.capture(
                distinct_id=request.user.distinct_id,
                event=event,
                properties={
                    "team_id": self.team_id,
                    "auth_method": "project_secret_api_key"
                    if is_authenticated_via_project_secret_api_key(request)
                    else "user",
                    "authorized_by": transactional_email_authorized_by(request, TRANSACTIONAL_EMAIL_SEND_SCOPE),
                    **properties,
                },
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email usage event", event_name=event, error=str(e))


class TemplateSourceSerializer(serializers.Serializer):
    repository = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        help_text="Host and path of the repository the file is in, such as `github.com/example/app`.",
    )
    path = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        help_text="Path of the template file in the repository, such as `emails/welcome.html`.",
    )
    ref = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        help_text="Commit or branch the file was uploaded from.",
    )


def with_field_named_source_that_drf_reserves(
    fields: dict[str, serializers.Field], source: TemplateSourceSerializer
) -> dict[str, serializers.Field]:
    return {**fields, "source": source}


class UploadTemplateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="Template name shown in the template library.")
    subject = serializers.CharField(
        trim_whitespace=False, help_text="Email subject line. Supports Liquid, such as `{{ variables.first_name }}`."
    )
    html = serializers.CharField(
        trim_whitespace=False,
        help_text="Email body as HTML, stored as sent. Supports Liquid, such as `{{ variables.first_name }}`.",
    )
    text = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Plain-text body for email clients that can't show HTML. Leaving it out removes the stored one.",
    )
    preheader = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Inbox preview text shown after the subject. Leaving it out removes the stored one.",
    )
    if_not_superseded = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Set it on uploads a program makes on its own, such as a sync that may hold an older copy of the "
        "file, or an upload after a send answered `template_outdated`. When newer content already replaced this content, "
        "the upload changes nothing and answers `superseded`. "
        "The check covers the last 100 different contents the template replaced. Content outside those 100 "
        "publishes. Leave it out to publish the content in any case, such as to roll back to earlier content.",
    )
    if_code_managed = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Set it so the upload only updates a template that code manages. When the key names a template "
        "edited in PostHog, the upload changes nothing and answers `409` with `template_edited_in_posthog`. A new "
        "key, or a template managed by code, uploads as usual. Leave it out to take over a template edited in "
        "PostHog, so code manages it from then on.",
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        return with_field_named_source_that_drf_reserves(
            super().get_fields(),
            TemplateSourceSerializer(
                required=False,
                help_text="Where the template file lives, so people in PostHog can find it. Leaving it out, or a "
                "part of it, keeps what is stored.",
            ),
        )


class UploadTemplateResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the template.")
    key = serializers.CharField(help_text="Key of the template.")
    result = serializers.ChoiceField(
        choices=TemplateUploadResult.choices,
        help_text="`created`: the upload made a new template. `updated`: it published the uploaded content. "
        "`unchanged`: the template already had this content, so nothing was published. `superseded`: the upload "
        "set `if_not_superseded` and newer content already replaced this content, so nothing was published.",
    )
    content_hash = serializers.CharField(
        help_text="Hash of the published content, as `v1:` and 64 hex characters. Send it with an email as "
        "`template_hash` to check PostHog holds the content you hold. After `superseded` it is the hash of the newer "
        "content."
    )
    managed_by = serializers.ChoiceField(
        choices=TemplateManagedBy.choices,
        allow_null=True,
        help_text="`code` after every upload except `superseded`, which changes nothing. After `superseded` it is "
        "what the template had, which is null for a template made in PostHog that no upload claimed yet.",
    )
    transactional_hog_flow_id = serializers.UUIDField(
        allow_null=True,
        help_text="The workflow that sends this template. Each upload that changes the content writes a new version "
        "of it. Null only after `superseded`, on a template that is not transactional yet.",
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        return with_field_named_source_that_drf_reserves(
            super().get_fields(),
            TemplateSourceSerializer(help_text="Where the template file lives, as stored after the upload."),
        )


TEMPLATE_KEY_PARAMETER = OpenApiParameter(
    name="key",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    description="Key of the template, chosen by you. Letters, digits, hyphens (-) and underscores (_), at most 400 "
    "characters. The same key names the template in every project.",
)


MANAGED_BY_CODE_RESPONSE = OpenApiResponse(
    response=TemplateErrorSerializer,
    description="The template is managed by code. `immutable`: change its file and upload it, or release it first",
)
TEMPLATE_UPDATE_SCHEMA = extend_schema(
    parameters=[TEMPLATE_ID_PARAMETER], responses={200: MessageTemplateSerializer, 403: MANAGED_BY_CODE_RESPONSE}
)
TEMPLATE_PARTIAL_UPDATE_SCHEMA = extend_schema(
    parameters=[TEMPLATE_ID_PARAMETER],
    request=MessageTemplateUpdateSerializer,
    responses={
        200: MessageTemplateSerializer,
        400: OpenApiResponse(
            response=TemplateErrorSerializer,
            description="A field is invalid. For `key`: `invalid_template_key`, `key_already_set`, `key_in_use`, or "
            "`invalid_request` when it is sent with other fields",
        ),
        403: MANAGED_BY_CODE_RESPONSE,
    },
)


@extend_schema_view(
    retrieve=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
    update=TEMPLATE_UPDATE_SCHEMA,
    partial_update=TEMPLATE_PARTIAL_UPDATE_SCHEMA,
    destroy=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
)
class MessageTemplatesViewSet(
    TransactionalEmailSendMixin,
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    # `design` is a custom write action; list it so programmatic callers (MCP/personal API key) get hog_flow:write
    # checked instead of being rejected as an action with no declared scope.
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "design",
        "upload",
    ]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["send", "upload"]
    transactional_email_send_actions = ("send",)
    # Access rules on hog_flow name workflow ids, never template ids, so no rule names one template.
    records_have_object_access_rules = False

    serializer_class = MessageTemplateSerializer

    def get_throttles(self):
        if self.action == "send":
            return transactional_email_throttles()
        if self.action == "upload":
            return template_upload_throttles()
        return super().get_throttles()

    def read_object(self) -> MessageTemplateRow | None:
        # Team scoping happens in the facade lookup, because the view has no queryset to filter.
        # DRF's detail OPTIONS metadata also calls get_object(), so the lookup must live here.
        try:
            # A send never reads the tags, so it skips their queries.
            return get_template(self.team_id, self.kwargs["pk"], with_tags=self.action != "send")
        except MessageTemplateMissing:
            return None

    def check_object_permissions(self, request: Request, obj: Any) -> None:
        super().check_object_permissions(request, obj)
        if request.method not in permissions.SAFE_METHODS:
            check_template_write(obj, self._write_intent())

    def _write_intent(self) -> TemplateWriteIntent:
        payload = self.request.data
        return TemplateWriteIntent(action=self.action, payload=payload if isinstance(payload, Mapping) else {})

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, TemplateWriteRefused):
            managed_by_code = isinstance(exc, TemplateManagedByCode)
            refusal = TemplateRefusal(
                code=exc.code, detail=exc.detail, attr=None if managed_by_code else "key", why=exc.why, fix=exc.fix
            )
            refused_status = status.HTTP_403_FORBIDDEN if managed_by_code else status.HTTP_400_BAD_REQUEST
            return Response(TemplateErrorSerializer(refusal).data, status=refused_status)
        return super().handle_exception(exc)

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
        self._report_user_action(
            "message_template_created",
            {"template_id": str(template.id), "organization_id": str(self.organization_id)},
        )
        data = self._serialize(template)
        return Response(data, status=status.HTTP_201_CREATED, headers=self.get_success_headers(data))

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        template = self.get_object()
        intent = self._write_intent()
        if is_release(intent):
            released = release_template(
                self.team_id, template.id, require_workflow_editor=self._require_workflow_editor
            )
            self._emit_resource_edited(released)
            if template.managed_by == TemplateManagedBy.CODE:
                self._report_user_action("message template released", {"template_id": str(released.id)})
            return Response(self._serialize(released))
        if is_adoption(intent):
            return self._adopt(template, intent)
        check_template_key_write(template, intent)
        serializer = self.get_serializer(self._with_creators([template])[0], data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        fields = serializer.validated_data
        if fields.keys() == {"draft_content"}:
            updated = save_template_draft(
                self.team_id,
                template.id,
                fields["draft_content"],
                intent=intent,
                require_workflow_editor=self._require_workflow_editor,
            )
            self._emit_resource_edited(updated)
            return Response(self._serialize(updated))
        if fields.keys() == {"tags"}:
            # Tags are library metadata. Sends never read them, so a tag edit skips the sendability check
            # and must not write a new version of the template's transactional workflow.
            updated = save_template_tags(self.team_id, template.id, fields["tags"])
            self._emit_resource_edited(updated)
            return Response(self._serialize(updated))
        if "content" in fields:
            fields["draft_content"] = None
        try:
            updated = save_template_fields(
                self.team_id,
                template.id,
                fields,
                intent=intent,
                user_id=self._actor_id(),
                require_workflow_editor=self._require_workflow_editor,
            )
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None
        self._emit_resource_edited(updated)
        return Response(self._serialize(updated))

    def _adopt(self, template: MessageTemplateRow, intent: TemplateWriteIntent) -> Response:
        key = intent.payload["key"]
        refused = invalid_template_key(key)
        if refused is not None:
            return Response(TemplateErrorSerializer(refused).data, status=status.HTTP_400_BAD_REQUEST)
        adopted = adopt_template(
            self.team_id, template.id, key, intent=intent, require_workflow_editor=self._require_workflow_editor
        )
        self._emit_resource_edited(adopted)
        self._report_user_action("message template adopted", {"template_id": str(adopted.id)})
        return Response(self._serialize(adopted))

    def _report_user_action(self, event: str, properties: dict[str, Any]) -> None:
        try:
            report_user_action(
                self.request.user,
                event,
                {"team_id": str(self.team_id), **properties},
                team=self.team,
                organization=self.organization,
                request=self.request,
            )
        except Exception as e:
            logger.warning("Failed to capture message template usage event", error=str(e))

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
        request=DesignPatchSerializer,
        responses={200: MessageTemplateSerializer, 403: MANAGED_BY_CODE_RESPONSE},
        parameters=[TEMPLATE_ID_PARAMETER],
    )
    @action(detail=True, methods=["PATCH"])
    def design(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Surgical design editing: apply a small, id-addressed op list to the stored Unlayer design instead
        # of re-transmitting the whole design JSON. Reads, applies, validates, re-renders, and saves
        # atomically so a rejected batch leaves the template untouched (and concurrent visual-editor saves
        # can't interleave).

        # Authorize + team-scope via the normal lookup, then re-read FOR UPDATE inside the transaction.
        template = self.get_object()

        op_serializer = DesignPatchSerializer(data=request.data)
        op_serializer.is_valid(raise_exception=True)
        operations = op_serializer.validated_data["operations"]

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

        try:
            saved = save_template_content(
                self.team_id,
                template.id,
                apply_operations,
                intent=self._write_intent(),
                user_id=self._actor_id(),
                require_workflow_editor=self._require_workflow_editor,
            )
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None

        self._emit_resource_edited(saved)
        return Response(self._serialize(saved))

    @validated_request(
        SendTransactionalEmailSerializer,
        responses=SEND_RESPONSES,
        summary="Send a transactional email",
        description=(
            "Send one transactional email from this template to one recipient. The template must be made "
            "transactional first. `message_data` fills the template's `{{ variables.* }}` placeholders. "
            "Transactional emails skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry "
            "safely without sending the email twice. Needs the `transactional_email:write` scope. A key with "
            "`hog_flow:write` also works, but that scope reaches the rest of Workflows too."
        ),
        parameters=[TEMPLATE_ID_PARAMETER, IDEMPOTENCY_KEY_PARAMETER],
    )
    @action(detail=True, methods=["POST"], pagination_class=None, required_scopes=[TRANSACTIONAL_EMAIL_SEND_SCOPE])
    def send(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self._end_request_validation()
        with transactional_email_stage("feature_flag"):
            self._require_transactional_email_flag()
        with transactional_email_stage("template_lookup"):
            template = self.get_object()
        return self._queue_transactional_email(request, template, route="template")

    @extend_schema(
        request=UploadTemplateSerializer,
        responses={
            200: OpenApiResponse(
                response=UploadTemplateResponseSerializer,
                description="The template was updated, is unchanged, or newer content superseded the upload",
            ),
            201: OpenApiResponse(response=UploadTemplateResponseSerializer, description="The template was created"),
            400: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="The key or a field is invalid, the template can't be sent, or there is no verified "
                "default sender",
            ),
            404: OpenApiResponse(description="Sending email from code is not enabled for this project"),
            409: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="The upload set `if_code_managed` and the template is edited in PostHog, so nothing "
                "changed",
            ),
            429: OpenApiResponse(description="Rate limited"),
        },
        summary="Upload a template by key",
        description=(
            "Create or update the email template with this key from HTML, for templates kept as files in a "
            "repository. The first upload creates the template and makes it transactional with the project's "
            "default verified sender. A later upload publishes changed content at once, and answers `unchanged` "
            "when the content is the same. With `if_not_superseded`, an upload of content that is one of the last "
            "100 different contents the template replaced changes nothing and answers `superseded`. With "
            "`if_code_managed`, an upload to a template edited in PostHog changes nothing and answers `409`. An "
            "upload keeps the template's sender and never turns a paused template back on."
        ),
        parameters=[TEMPLATE_KEY_PARAMETER],
    )
    @action(detail=False, methods=["PUT"], url_path=r"by_key/(?P<key>[^/]+)", pagination_class=None)
    def upload(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        require_email_from_code(self.team)
        refused = invalid_template_key(key)
        body = UploadTemplateSerializer(data=request.data)
        if refused is None and not body.is_valid():
            refused = invalid_request(
                body.errors, why="An upload needs a name, a subject and HTML, each as a string.", retry="upload again"
            )
        if refused is not None:
            self._report_template_upload(request, {"result": "rejected", "error_code": refused.code})
            return Response(TemplateErrorSerializer(refused).data, status=status.HTTP_400_BAD_REQUEST)

        try:
            uploaded = upload_template(
                self.team_id,
                self._template_upload(key, body.validated_data),
                user_id=self._actor_id(),
                require_workflow_editor=self._require_workflow_editor,
                require_workflow_create=self._require_workflow_create,
            )
        except TemplateEditedInPostHog as e:
            self._report_template_upload(request, {"result": "rejected", "error_code": e.code})
            return Response(TemplateErrorSerializer(template_edited_in_posthog()).data, status=status.HTTP_409_CONFLICT)
        except TransactionalEmailError as e:
            self._report_template_upload(request, {"result": "rejected", "error_code": e.code})
            raise TransactionalEmailRejected(e) from None
        except exceptions.PermissionDenied:
            self._report_template_upload(request, {"result": "rejected", "error_code": "permission_denied"})
            raise

        self._report_template_upload(request, {"result": uploaded.result, "template_id": str(uploaded.template.id)})
        if uploaded.result != TemplateUploadResult.SUPERSEDED:
            self._emit_resource_edited(uploaded.template)
        created = uploaded.result == TemplateUploadResult.CREATED
        return Response(
            UploadTemplateResponseSerializer(self._upload_response(uploaded)).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @staticmethod
    def _template_upload(key: str, data: dict[str, Any]) -> TemplateUpload:
        source = data.get("source")
        return TemplateUpload(
            key=key,
            name=data["name"],
            subject=data["subject"],
            html=data["html"],
            text=data.get("text", ""),
            preheader=data.get("preheader", ""),
            design=build_html_wrap_design(data["html"]),
            source=TemplateSource(repository=source.get("repository"), path=source.get("path"), ref=source.get("ref"))
            if source
            else None,
            if_not_superseded=data["if_not_superseded"],
            if_code_managed=data["if_code_managed"],
        )

    @staticmethod
    def _upload_response(uploaded: UploadedTemplate) -> dict[str, Any]:
        template = uploaded.template
        return {
            "id": template.id,
            "key": template.key,
            "result": uploaded.result,
            "content_hash": template.content_hash,
            "managed_by": template.managed_by,
            "source": {
                "repository": template.source_repository,
                "path": template.source_path,
                "ref": template.source_ref,
            },
            "transactional_hog_flow_id": template.transactional_hog_flow_id,
        }

    def _report_template_upload(self, request: Any, outcome: dict[str, Any]) -> None:
        self._capture_api_usage(request, "transactional email template uploaded", outcome)

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
            "nothing. Needs the `transactional_email:write` scope, the same scope as sending. A key with "
            "`hog_flow:write` also works, but that scope reaches the rest of Workflows too. Without `hog_flow:read`, "
            "the response leaves out `content` and `draft_content`."
        ),
        parameters=[TEMPLATE_ID_PARAMETER],
    )
    @action(detail=True, methods=["POST"], pagination_class=None, required_scopes=[TRANSACTIONAL_EMAIL_SEND_SCOPE])
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
            self._report_user_action("message template made transactional", {"template_id": str(template.id)})
        data = self._serialize(updated)
        # A send-scoped key can't read templates, so converting one must not hand it their content.
        if scopes_caller_lacks(request, ["hog_flow:read"]):
            data.pop("content", None)
            data.pop("draft_content", None)
        return Response(data)


class MessagingSendViewSet(TransactionalEmailSendMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["email"]
    transactional_email_send_actions = ("email",)
    # Access rules on hog_flow name workflow ids, never template ids, so no rule names one template.
    records_have_object_access_rules = False

    def get_throttles(self):
        return transactional_email_throttles()

    def read_object(self) -> MessageTemplateRow | None:
        # The `email` action names its template in the request body, not in the URL.
        try:
            return get_template(self.team_id, self.request.validated_data["template_id"], with_tags=False)
        except MessageTemplateMissing:
            return None

    def handle_exception(self, exc: Exception) -> Response:
        response = super().handle_exception(exc)
        if isinstance(response.data, dict):
            response.data = with_code_send_reason(response.data)
        return response

    @validated_request(
        SendEmailSerializer,
        responses={
            **SEND_RESPONSES,
            202: OpenApiResponse(response=SendEmailResponseSerializer, description="Email queued"),
        },
        summary="Send a transactional email",
        description=(
            "Send one transactional email to one recipient. Name a template made transactional in `template_id`, or "
            "one uploaded from code in `template_key`, and `message_data` fills its `{{ variables.* }}` placeholders. "
            "Or send content your code rendered with "
            "a `template_key`, a `subject` and `html` or `text`: PostHog sends it as is, and its metrics and run "
            "history group under the key. Transactional emails skip opt-outs and frequency caps. Send an "
            "`Idempotency-Key` header to retry safely without sending the email twice. Needs the "
            "`transactional_email:write` scope. A key with `hog_flow:write` also works, but that scope reaches the "
            "rest of Workflows too."
        ),
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
    )
    @action(detail=False, methods=["POST"], required_scopes=[TRANSACTIONAL_EMAIL_SEND_SCOPE])
    def email(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self._end_request_validation()
        if sends_uploaded_template(request.validated_data):
            return self._send_uploaded_template(request)
        if "template_key" in request.validated_data:
            return self._send_code_email(request)
        with transactional_email_stage("feature_flag"):
            self._require_transactional_email_flag()
            self._refuse_engagement_capture_outside_the_beta(request.data)
        with transactional_email_stage("template_lookup"):
            template = self.get_object()
        return self._queue_transactional_email(
            request, template, route="send_email", options=_id_send_options(request.data, request.validated_data)
        )

    def _refuse_engagement_capture_outside_the_beta(self, sent: Mapping[str, Any]) -> None:
        if "capture_engagement" in sent and not _flag_enabled(self.team, EMAIL_FROM_CODE_FLAG):
            raise serializers.ValidationError({"capture_engagement": ENGAGEMENT_CAPTURE_OUTSIDE_THE_BETA})

    def _send_uploaded_template(self, request: Any) -> Response:
        with transactional_email_stage("feature_flag"):
            require_email_from_code(self.team)
        data = request.validated_data
        with transactional_email_stage("template_lookup"):
            try:
                found = find_template_to_send(self.team_id, data["template_key"], data.get("template_hash"))
            except MessageTemplateMissing:
                if "template_hash" in data:
                    raise TransactionalEmailRejected(TemplateOutdated(TEMPLATE_OUTDATED_DETAIL)) from None
                raise TemplateKeyNotFound() from None
            self.check_object_permissions(request, found.template)
        template = found.template
        with transactional_email_stage("workflow_access"):
            if template.transactional_hog_flow_id:
                self._require_workflow_editor(template.transactional_hog_flow_id)
        options = _template_send_options(data)

        def send(idempotency_key: str | None) -> QueuedEmail:
            if found.hash_state == ContentHashState.OUTDATED:
                raise TemplateOutdated(TEMPLATE_OUTDATED_DETAIL)
            return send_transactional_email(
                self.team,
                template.id,
                to=data["to"],
                distinct_id=_distinct_id(data),
                message_data=data["message_data"],
                idempotency_key=idempotency_key,
                options=options,
            )

        return self._queue_send(
            request,
            send,
            route="send_email",
            addressed={
                "addressed_by": "uploaded_template_key",
                "template_id": str(template.id),
                "hash_state": str(found.hash_state),
            },
            unavailable=UnconfirmedEmailSend,
            warnings=[TEMPLATE_SUPERSEDED_WARNING] if found.hash_state == ContentHashState.SUPERSEDED else [],
        )

    def _send_code_email(self, request: Any) -> Response:
        with transactional_email_stage("feature_flag"):
            require_email_from_code(self.team)
        data = request.validated_data
        key = data["template_key"]
        with transactional_email_stage("workflow_access"):
            require_code_email_access(
                self.team_id,
                key,
                require_workflow_editor=self._require_workflow_editor,
                require_workflow_create=self._require_workflow_create,
            )
        email = CodeEmail(
            key=key,
            subject=data["subject"],
            html=data.get("html", ""),
            text=data.get("text", ""),
            sender=data.get("from"),
            reply_to=tuple(data.get("reply_to", ())),
            capture_engagement=data.get("capture_engagement", True),
            cc=tuple(data.get("cc") or ()),
            bcc=tuple(data.get("bcc") or ()),
            attachments=tuple(EmailAttachment(**attachment) for attachment in data.get("attachments") or ()),
        )
        return self._queue_send(
            request,
            lambda idempotency_key: send_code_email(
                self.team,
                email,
                to=data["to"],
                distinct_id=_distinct_id(data),
                idempotency_key=idempotency_key,
            ),
            route="send_email",
            addressed={"addressed_by": "template_key"},
            unavailable=UnconfirmedEmailSend,
        )


TEMPLATE_OUTDATED_DETAIL = (
    "PostHog doesn't hold the content `template_hash` describes, so nothing was sent. Upload the template, then send "
    "again."
)
ENGAGEMENT_CAPTURE_OUTSIDE_THE_BETA = (
    "A send with `template_id` takes this field only in the beta for sending email from code. Remove it to send the "
    "email."
)


def _id_send_options(sent: Mapping[str, Any], data: Mapping[str, Any]) -> TemplateSendOptions | None:
    return _template_send_options(data) if "capture_engagement" in sent else None


def _template_send_options(data: Mapping[str, Any]) -> TemplateSendOptions:
    return TemplateSendOptions(
        sender=data.get("from"),
        reply_to=tuple(data.get("reply_to", ())),
        capture_engagement=data.get("capture_engagement", True),
    )


def _distinct_id(data: Mapping[str, Any]) -> str | None:
    return data.get("distinct_id") or (data.get("identifiers") or {}).get("distinct_id") or None
