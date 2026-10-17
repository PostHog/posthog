from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.dataclasses import frozen

from products.messaging.backend.facade.contracts import ContentHashState, QueuedEmail, TemplateReference
from products.messaging.backend.facade.templates import MessageTemplateMissing, find_template_to_send
from products.messaging.backend.presentation.views.transactional_email_api import (
    TRANSACTIONAL_EMAIL_THROTTLES,
    SendTransactionalEmailResponseSerializer,
    SendTransactionalEmailSerializer,
    TemplateErrorSerializer,
    TemplateRefusal,
    TransactionalEmailViewSetMixin,
    invalid_request,
    invalid_template_key,
)


class TemplateReferenceSerializer(serializers.Serializer):
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


class SendEmailSerializer(SendTransactionalEmailSerializer):
    template = TemplateReferenceSerializer(help_text="The template to send, by key or by id.")


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


def invalid_send(errors: Any) -> TemplateRefusal:
    return invalid_request(
        errors, why="A send needs a template, a recipient address, and data as an object.", retry="send again"
    )


def template_not_found(reference: TemplateReference) -> TemplateRefusal:
    if reference.key is not None:
        return TemplateRefusal(
            code="template_not_found",
            detail=f"No template in this project has the key `{reference.key}`.",
            attr="template__key",
            why="A send names a template of this project that is not deleted.",
            fix=f"Upload the template first with `PUT /api/projects/@current/messaging_templates/by_key/{reference.key}/`, "
            "or check the key and the project.",
        )
    return TemplateRefusal(
        code="template_not_found",
        detail=f"No template in this project has the id `{reference.id}`.",
        attr="template__id",
        why="A send names a template of this project that is not deleted.",
        fix="Check the id and the project.",
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
                description="No template has this key or id, or the transactional email API is not enabled",
            ),
            409: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="PostHog does not hold the content the hash describes. Nothing was sent",
            ),
            429: OpenApiResponse(description="Rate limited, or the project is over its email quota"),
            503: OpenApiResponse(description="The email pipeline did not confirm the send"),
        },
        summary="Send a transactional email",
        description=(
            "Send one transactional email to one recipient from a template named by its key or id. `message_data` "
            "fills the template's `{{ variables.* }}` placeholders. With `template.hash`, PostHog checks that it "
            "holds the content you hold: content it never published sends nothing, and content that newer content "
            "replaced sends the current content with a `template_superseded` warning. Transactional emails skip "
            "opt-outs and frequency caps."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="send/email")
    def send_email(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()
        body = SendEmailSerializer(data=request.data)
        if not body.is_valid():
            return self._refuse(invalid_send(body.errors))
        reference = template_reference(body.validated_data["template"])
        if reference.key is not None and (refused := invalid_template_key(reference.key, attr="template__key")):
            return self._refuse(refused)

        addressed_by = "key" if reference.key is not None else "id"
        try:
            target = find_template_to_send(self.team_id, reference)
        except MessageTemplateMissing:
            return self._refuse(template_not_found(reference), status.HTTP_404_NOT_FOUND, addressed_by=addressed_by)
        usage = {"addressed_by": addressed_by, "hash_state": target.hash_state.value}
        if target.hash_state == ContentHashState.OUTDATED:
            return self._refuse(
                TEMPLATE_OUTDATED, status.HTTP_409_CONFLICT, template_id=str(target.template.id), **usage
            )

        queued = self._send_transactional_email(request, target.template, body.validated_data, usage=usage)
        return self._queued(queued, target.hash_state)

    @staticmethod
    def _queued(queued: QueuedEmail, hash_state: ContentHashState) -> Response:
        warnings = [TEMPLATE_SUPERSEDED] if hash_state == ContentHashState.SUPERSEDED else []
        return Response(
            SendEmailResponseSerializer({"message_id": queued.message_id, "warnings": warnings}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def _refuse(
        self, refused: TemplateRefusal, status_code: int = status.HTTP_400_BAD_REQUEST, **usage: str
    ) -> Response:
        if usage:
            self._report_transactional_email_send(
                self.request, {**usage, "outcome": "rejected", "error_code": refused.code}
            )
        return Response(TemplateErrorSerializer(refused).data, status=status_code)
