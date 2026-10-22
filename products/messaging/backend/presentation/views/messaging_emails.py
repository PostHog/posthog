from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import ProjectSecretAPIKeyAuthentication

from products.messaging.backend.facade.email_status import EmailStatus, EmailStatusRecord, get_email_status
from products.messaging.backend.presentation.views.transactional_email_api import (
    TRANSACTIONAL_EMAIL_THROTTLES,
    TemplateErrorSerializer,
    TemplateRefusal,
    TransactionalEmailViewSetMixin,
)


class EmailStatusSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The email's `message_id`, as the send answered it.")
    status = serializers.ChoiceField(
        choices=EmailStatus.choices,
        help_text="Where the email is. A status never moves back: a late `sent` never replaces `delivered`.",
    )
    created_at = serializers.DateTimeField(help_text="When PostHog accepted the send.")
    status_at = serializers.DateTimeField(help_text="When the email reached its status.")
    reason = serializers.CharField(
        required=False,
        help_text="Why the email is `skipped`, `failed`, `bounced` or `complained`, such as `recipient_suppressed`, "
        "`provider_error` or `hard`. Absent for the other statuses.",
    )

    def to_representation(self, instance: EmailStatusRecord) -> dict[str, Any]:
        representation = {
            "id": instance.message_id,
            "status": instance.status.value,
            "created_at": instance.created_at,
            "status_at": instance.status_at,
        }
        if instance.reason:
            representation["reason"] = instance.reason
        return super().to_representation(representation)


def email_not_found(message_id: str) -> TemplateRefusal:
    return TemplateRefusal(
        code="not_found",
        detail=f"No email in this project has the id `{message_id}`.",
        attr=None,
        why="PostHog keeps an email's status for 30 days. A new email can take a few seconds to show up.",
        fix="Check the `message_id` the send answered and the project, or read again in a few seconds.",
        type="invalid_request",
    )


class MessagingEmailsViewSet(TransactionalEmailViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["retrieve"]
    throttle_classes = TRANSACTIONAL_EMAIL_THROTTLES

    @extend_schema(
        responses={
            200: OpenApiResponse(response=EmailStatusSerializer, description="The email's latest status"),
            404: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="No email in this project has this id, it is older than 30 days, or it was sent a few "
                "seconds ago and has not shown up yet",
            ),
            429: OpenApiResponse(response=TemplateErrorSerializer, description="Rate limited, retry later"),
        },
        summary="Get a transactional email's status",
        description="Read where an email sent with `POST /api/projects/@current/messaging/send/email/` is, by the "
        "`message_id` the send answered.",
    )
    def retrieve(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()
        record = self._status(pk)
        if record is None:
            return Response(TemplateErrorSerializer(email_not_found(pk)).data, status=status.HTTP_404_NOT_FOUND)
        return Response(EmailStatusSerializer(record).data)

    def _status(self, message_id: str) -> EmailStatusRecord | None:
        try:
            parsed = UUID(message_id)
        except ValueError:
            return None
        return get_email_status(self.team_id, parsed)
