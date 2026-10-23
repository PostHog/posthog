from collections.abc import Mapping
from email.utils import parseaddr
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.dataclasses import frozen

from products.messaging.backend.facade.contracts import ContentHashState, Queued, TemplateReference
from products.messaging.backend.facade.templates import MessageTemplateMissing, find_template_to_send
from products.messaging.backend.facade.transactional_email import (
    SENDER_ADDRESS_MAX_LENGTH,
    SENDER_ADDRESS_PATTERN,
    AcceptedSend,
    EmailSendCommand,
    RenderedContent,
    RenderedEmail,
    SenderNotVerified,
    code_send_from,
    rendered_content,
    require_code_email_access,
)
from products.messaging.backend.presentation.views.send_email_fields import PlainAddressField
from products.messaging.backend.presentation.views.transactional_email_api import (
    TRANSACTIONAL_EMAIL_THROTTLES,
    SendTransactionalEmailResponseSerializer,
    SendTransactionalEmailSerializer,
    TemplateErrorSerializer,
    TemplateRefusal,
    TransactionalEmailIdentifiersSerializer,
    TransactionalEmailViewSetMixin,
    first_field_error,
    invalid_request,
    invalid_template_key,
)


class RefusesUnknownFieldsSerializer(serializers.Serializer):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, Mapping):
            unknown = [field for field in data if field not in self.fields]
            if unknown:
                raise serializers.ValidationError({unknown[0]: "PostHog doesn't take this field on this route."})
        return super().to_internal_value(data)


class TemplateReferenceSerializer(RefusesUnknownFieldsSerializer):
    key = serializers.CharField(
        required=False,
        trim_whitespace=False,
        help_text="Key of the template, as uploaded with `PUT /api/projects/@current/messaging_templates/by_key/{key}/`. "
        "Give either `key` or `id`.",
    )
    hash = serializers.CharField(
        required=False,
        help_text="Content hash of the template you hold, as `v1:` and 64 hex characters. When PostHog never "
        "published that content, the send answers `template_outdated` and sends nothing. Only with `key`.",
    )
    id = serializers.UUIDField(
        required=False,
        help_text="ID of the template, for templates made in PostHog. Give either `key` or `id`.",
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if ("key" in data) == ("id" in data) or ("hash" in data and "id" in data):
            raise serializers.ValidationError("Name the template with either `key` (and an optional `hash`) or `id`.")
        return data


CODE_FORM_FIELDS = ("subject", "html", "text")


class SendIdentifiersSerializer(RefusesUnknownFieldsSerializer, TransactionalEmailIdentifiersSerializer):
    pass


class SendEmailSerializer(RefusesUnknownFieldsSerializer, SendTransactionalEmailSerializer):
    to = PlainAddressField(help_text="Email address of the recipient, as `jane@example.com`.")
    identifiers = SendIdentifiersSerializer(
        required=False, help_text="Who the email is for, used to attribute engagement events."
    )
    template = TemplateReferenceSerializer(
        required=False,
        help_text="The template to send, by key or by id. Leave it out to send content your code rendered, with "
        "`template_key`.",
    )
    template_key = serializers.CharField(
        required=False,
        trim_whitespace=False,
        help_text="Names an email whose content your code rendered, such as `password-reset`, so its metrics, logs "
        "and status group under it. Send it with `subject` and `html` or `text`, instead of `template`. PostHog "
        "sends the content as is and never stores it as a template.",
    )
    subject = serializers.CharField(
        required=False, trim_whitespace=False, help_text="Subject of the rendered email. Only with `template_key`."
    )
    html = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="HTML body of the rendered email. Only with `template_key`.",
    )
    text = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Plain text body of the rendered email. Only with `template_key`. Without it, PostHog derives the "
        "text from `html`.",
    )
    from_address = serializers.CharField(
        required=False,
        help_text="Sender, as `security@example.com` or `Example <security@example.com>`, on a verified domain of "
        "the project. Without it, rendered content goes out from the project's default sender, and a template from "
        "its own sender. Not with `template.id`.",
    )
    reply_to = serializers.ListField(
        child=PlainAddressField(),
        required=False,
        allow_empty=False,
        max_length=10,
        help_text="Addresses replies go to. Not with `template.id`.",
    )
    capture_engagement = serializers.BooleanField(
        required=False,
        help_text="Whether the email's engagement events (sent, delivered, opened, clicked, bounced) are captured "
        "as analytics events of the recipient. They count as analytics events. Defaults to on for `template_key` and "
        "`template.key` sends, and to the project's setting for `template.id` sends.",
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        # `from` is a Python keyword, so the field is declared under another name.
        fields["from"] = fields.pop("from_address")
        return fields

    def validate_from(self, value: str) -> str:
        _name, address = parseaddr(value)
        if not self._is_sender_address(address):
            raise serializers.ValidationError("Enter an address, such as `Example <security@example.com>`.")
        return value

    @staticmethod
    def _is_sender_address(address: str) -> bool:
        # The email worker ignores an address its pattern refuses and sends from the sender's own address instead.
        if len(address) > SENDER_ADDRESS_MAX_LENGTH or not SENDER_ADDRESS_PATTERN.match(address):
            return False
        try:
            validate_email(address)
        except DjangoValidationError:
            return False
        return True

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if ("template" in data) == ("template_key" in data):
            raise serializers.ValidationError(
                {"template_key": "Send either `template`, or `template_key` with the content your code rendered."}
            )
        if "template_key" in data:
            self._validate_rendered_content(data)
        else:
            self._validate_template_send(data)
        return data

    def _validate_rendered_content(self, data: dict[str, Any]) -> None:
        if not data.get("subject"):
            raise serializers.ValidationError({"subject": "Rendered content needs a subject."})
        if not (data.get("html") or data.get("text")):
            raise serializers.ValidationError({"html": "Rendered content needs `html`, `text` or both."})
        if "message_data" in self.initial_data:
            raise serializers.ValidationError(
                {"message_data": "Rendered content takes no data. To fill a template, send `template` with its key."}
            )

    @staticmethod
    def _validate_template_send(data: dict[str, Any]) -> None:
        for field in CODE_FORM_FIELDS:
            if field in data:
                raise serializers.ValidationError({field: "Only with `template_key`."})
        if "id" in data["template"]:
            for field in ("from", "reply_to"):
                if field in data:
                    raise serializers.ValidationError({field: "Not with `template.id`. The template's sender applies."})


class SendEmailWarningSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable warning code to branch on, such as `template_superseded`.")
    detail = serializers.CharField(help_text="What happened.")
    fix = serializers.CharField(help_text="What you can change, if the warning is not what you want.")


class SendEmailResponseSerializer(SendTransactionalEmailResponseSerializer):
    warnings = SendEmailWarningSerializer(
        many=True, help_text="Things to know about the queued email. Empty in the normal case."
    )


@frozen
class SendWarning:
    code: str
    detail: str
    fix: str


TEMPLATE_SUPERSEDED = SendWarning(
    code="template_superseded",
    detail="The email was sent with the template's current content, because newer content replaced the content you "
    "hold.",
    fix="Deploy the newer file, or upload your file to publish it again.",
)


def template_reference(template: dict[str, Any]) -> TemplateReference:
    return TemplateReference(key=template.get("key"), id=template.get("id"), hash=template.get("hash"))


RENDERED_CONTENT_WHY = (
    "Content your code rendered goes out as is, so it needs a `subject` and an `html` or `text` body. A template "
    "send takes all three from the template."
)
SEND_FIELD_WHY = {
    "to": "PostHog sends each email to one recipient, so `to` must be one email address.",
    "identifiers": "PostHog records the email's engagement events against `identifiers.distinct_id`.",
    "message_data": "`message_data` fills a template's `{{ variables.* }}` placeholders, so it is an object, and "
    "content your code rendered takes none.",
    "template": "A `template` send names one template, by its key or by its id.",
    "template_key": "A send is either a `template`, or content your code rendered under a `template_key`.",
    "subject": RENDERED_CONTENT_WHY,
    "html": RENDERED_CONTENT_WHY,
    "text": RENDERED_CONTENT_WHY,
    "from": "PostHog sends from an address on a verified domain, given in `from`. A template made in PostHog keeps "
    "its own sender.",
    "reply_to": "Replies go to the addresses in `reply_to`. A template made in PostHog keeps its own reply-to.",
    "capture_engagement": "`capture_engagement` turns the email's engagement events on or off, so it is true or false.",
}


def invalid_send(errors: Any) -> TemplateRefusal:
    return invalid_request(errors, why=send_field_why(first_field_error(errors).attr), retry="send again")


def send_field_why(attr: str | None) -> str:
    field = attr.split("__")[0] if attr else ""
    if field in SEND_FIELD_WHY:
        return SEND_FIELD_WHY[field]
    if not field:
        return "A send needs a template, a recipient address, and data as an object."
    return (
        f"PostHog refuses a field it doesn't know, such as `{field}` from a newer SDK, so it never sends the email "
        "without part of what you asked for."
    )


def key_not_held(key: str) -> TemplateRefusal:
    return TemplateRefusal(
        code="template_outdated",
        detail=f"No template in this project has the key `{key}`, so nothing was sent.",
        attr="template__key",
        why="PostHog holds no content for this key yet.",
        fix=f"Upload the template with `PUT /api/projects/@current/messaging_templates/by_key/{key}/`, then send "
        "again. posthog-node does this on its own.",
    )


def id_not_found(template_id: UUID | None) -> TemplateRefusal:
    return TemplateRefusal(
        code="template_not_found",
        detail=f"No template in this project has the id `{template_id}`.",
        attr="template__id",
        why="A send names a template of this project that is not deleted.",
        fix="Check the id and the project.",
    )


def sender_not_verified(detail: str) -> TemplateRefusal:
    return TemplateRefusal(
        code="sender_not_verified",
        detail=detail,
        attr="from",
        why="PostHog only sends from a domain the project verified, so mailbox providers trust the email.",
        fix="Send from an address on a verified domain, or verify the domain in the email channel settings first.",
    )


TEMPLATE_OUTDATED = TemplateRefusal(
    code="template_outdated",
    detail="PostHog does not hold the content this hash describes, so nothing was sent.",
    attr="template__hash",
    why="The template never had this content, so sending its current content could send the wrong email.",
    fix="Upload the template, then send again. posthog-node does this on its own.",
)


class MessagingSendViewSet(TransactionalEmailViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    scope_object_write_actions = ["send_email"]
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["send_email"]
    throttle_classes = TRANSACTIONAL_EMAIL_THROTTLES

    @extend_schema(
        request=SendEmailSerializer,
        responses={
            202: OpenApiResponse(response=SendEmailResponseSerializer, description="Email queued"),
            400: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="A field is invalid, the template isn't transactional or its email is paused, or the "
                "recipient can't be used",
            ),
            404: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="No template has this id, or the transactional email API is not enabled",
            ),
            409: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="PostHog holds no template with this key, or not the content the hash describes. "
                "Nothing was sent",
            ),
            429: OpenApiResponse(description="Rate limited, or the project is over its email quota"),
            503: OpenApiResponse(description="The email pipeline did not confirm the send"),
        },
        summary="Send a transactional email",
        description=(
            "Send one transactional email to one recipient, in one of two forms. A template named by its key or id: "
            "`message_data` fills its `{{ variables.* }}` placeholders. With `template.hash`, PostHog checks that it "
            "holds the content you hold: a key or content it doesn't hold sends nothing and answers "
            "`template_outdated`, and content that newer content replaced sends the current content with a "
            "`template_superseded` warning. Or content your code rendered, named by `template_key`: PostHog sends "
            "it as is and never stores it. Transactional emails skip opt-outs and frequency caps."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="send/email")
    def send_email(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()
        body = SendEmailSerializer(data=request.data)
        if not body.is_valid():
            return self._refuse(invalid_send(body.errors))
        data = body.validated_data
        if "template_key" in data:
            return self._send_rendered_content(request, data)
        reference = template_reference(data["template"])
        if reference.key is not None and (refused := invalid_template_key(reference.key, attr="template__key")):
            return self._refuse(refused)

        addressed_by = "key" if reference.key is not None else "id"
        try:
            target = find_template_to_send(self.team_id, reference)
        except MessageTemplateMissing:
            if reference.key is not None:
                return self._refuse(
                    key_not_held(reference.key), status.HTTP_409_CONFLICT, usage={"addressed_by": addressed_by}
                )
            return self._refuse(
                id_not_found(reference.id), status.HTTP_404_NOT_FOUND, usage={"addressed_by": addressed_by}
            )
        usage = {"addressed_by": addressed_by, "hash_state": target.hash_state.value}
        if target.hash_state == ContentHashState.OUTDATED:
            return self._refuse(
                TEMPLATE_OUTDATED, status.HTTP_409_CONFLICT, usage={**usage, "template_id": str(target.template.id)}
            )

        try:
            send = self._accepted_send(data, content=None) if reference.key is not None else self._tracking_only(data)
        except SenderNotVerified as e:
            return self._refuse(sender_not_verified(str(e)), usage={**usage, "template_id": str(target.template.id)})
        queued = self._send_transactional_email(request, target.template, data, usage=usage, send=send)
        warnings = [TEMPLATE_SUPERSEDED] if target.hash_state == ContentHashState.SUPERSEDED else []
        return self._queued(queued, warnings)

    def _send_rendered_content(self, request: Request, data: dict[str, Any]) -> Response:
        key = data["template_key"]
        if refused := invalid_template_key(key, attr="template_key"):
            return self._refuse(refused)
        require_code_email_access(
            self.team_id,
            key,
            require_workflow_editor=self._require_workflow_editor,
            require_workflow_create=self._require_workflow_create,
        )
        usage = {"addressed_by": "template_key"}
        content = rendered_content(subject=data["subject"], html=data.get("html", ""), text=data.get("text", ""))
        try:
            send = self._accepted_send(data, content=content)
        except SenderNotVerified as e:
            return self._refuse(sender_not_verified(str(e)), usage=usage)
        command = EmailSendCommand(
            team_id=self.team_id,
            to=data["to"],
            distinct_id=self._distinct_id(data),
            source=RenderedEmail(key=key, send=send),
        )
        return self._queued(self._send(request, command, report=usage), [])

    def _accepted_send(self, data: dict[str, Any], *, content: RenderedContent | None) -> AcceptedSend:
        capture = data.get("capture_engagement")
        # Rendered content has no template sender to fall back on, so it always names one.
        needs_sender = content is not None or "from" in data
        return AcceptedSend(
            content=content,
            sender=code_send_from(self.team_id, data.get("from")) if needs_sender else None,
            reply_to=tuple(data.get("reply_to", ())),
            capture_engagement=True if capture is None else capture,
        )

    @staticmethod
    def _tracking_only(data: dict[str, Any]) -> AcceptedSend | None:
        """A template made in PostHog keeps the project's capture setting unless the caller chooses."""
        capture = data.get("capture_engagement")
        if capture is None:
            return None
        return AcceptedSend(content=None, sender=None, reply_to=(), capture_engagement=capture)

    @staticmethod
    def _queued(queued: Queued, warnings: list[SendWarning]) -> Response:
        return Response(
            SendEmailResponseSerializer(
                {"message_id": queued.message_id, "replayed": queued.replayed, "warnings": warnings}
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def _refuse(
        self,
        refused: TemplateRefusal,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        *,
        usage: Mapping[str, str] | None = None,
    ) -> Response:
        if usage:
            self._report_transactional_email_send(
                self.request, {**usage, "outcome": "rejected", "error_code": refused.code}
            )
        return Response(TemplateErrorSerializer(refused).data, status=status_code)
