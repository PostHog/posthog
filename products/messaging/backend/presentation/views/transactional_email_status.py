from typing import Any
from uuid import UUID

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.event_usage import groups
from posthog.permissions import is_authenticated_via_project_secret_api_key

from products.messaging.backend.facade.transactional_email import EmailSendStatus, EmailStatus, get_email_status
from products.messaging.backend.presentation.views.transactional_email_access import (
    TRANSACTIONAL_EMAIL_STATUS_SCOPE,
    require_email_status_read,
    transactional_email_authorized_by,
    transactional_email_read_throttles,
)

logger = structlog.get_logger(__name__)

MESSAGE_ID_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="The `message_id` that the send returned.",
)


class EmailStatusSerializer(serializers.Serializer):
    id = serializers.CharField(source="message_id", help_text="The `message_id` that the send returned.")
    status = serializers.ChoiceField(
        choices=EmailSendStatus.choices,
        help_text="What happened to the email. `scheduled` means it waits for the time it was scheduled for, and "
        "`canceled` means it was canceled before it went out. `queued` means it waits to go out. `sent` means PostHog handed it to "
        "the email provider. `failed` means it was not sent, and `reason` says why. A rerun of the send can still move it to `sent`. `delivered` means the recipient's "
        "mail server accepted it. `bounced` and `complained` come later from the recipient's mail provider.",
    )
    created_at = serializers.DateTimeField(help_text="When the send was queued.")
    status_at = serializers.DateTimeField(help_text="When the email reached its current status.")
    reason = serializers.CharField(
        allow_null=True,
        help_text="Why a failed email was not sent, or the bounce type of a bounced email. A failed send has "
        "`provider_error`, or `provider_rejected` when the provider refused the email after it accepted the send. A skipped send has `recipient_suppressed`, `recipient_unreachable`, `recipient_opted_out`, "
        "`missing_recipient`, `sending_paused`, `sending_suspended` or `frequency_capped`. A run that stopped before "
        "the send has `canceled`, `workflow_unavailable` or an error kind such as `timeout`, and more error kinds can "
        "be added. A bounce has `hard`, `soft` or `unknown`. Null otherwise.",
    )


class MessagingEmailsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    required_scopes = [TRANSACTIONAL_EMAIL_STATUS_SCOPE]
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["retrieve"]

    def get_throttles(self) -> list[BaseThrottle]:
        # Only a project secret API key can read, and the email read buckets count those. Any other caller gets the
        # default API throttles on its way to a 401.
        if not is_authenticated_via_project_secret_api_key(self.request):
            return super().get_throttles()
        return transactional_email_read_throttles()

    @extend_schema(
        parameters=[MESSAGE_ID_PARAMETER],
        responses={
            200: EmailStatusSerializer,
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: OpenApiResponse(
                description="No email of this project has this ID, or it is older than 60 days. In the first "
                "seconds after a send, it means the email is queued but its first status isn't recorded yet."
            ),
        },
        summary="Get a transactional email's status",
        description=(
            "Get the status of one transactional email by the `message_id` that the send returned, for 60 days after "
            "the send. Needs a project secret API key with the `transactional_email:read` scope. A key with "
            "`hog_flow:read` also works, but that scope reaches the rest of Workflows too. The first status is "
            "recorded a few seconds after the send, so a read right after a send can answer 404. Treat that 404 as "
            "`queued` and read again a few seconds later."
        ),
    )
    def retrieve(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        # The routing mixin adds session and personal API key authentication to every route. A status is read by the
        # server that sent the email, so only its project secret API key can read it.
        if not is_authenticated_via_project_secret_api_key(request):
            raise exceptions.NotAuthenticated()
        require_email_status_read(self.team)
        email_status = self._email_status(pk)
        self._report_status_read(request, email_status)
        if email_status is None:
            raise NotFound()
        return Response(EmailStatusSerializer(email_status).data)

    def _email_status(self, pk: str | None) -> EmailStatus | None:
        try:
            message_id = UUID(str(pk))
        except ValueError:
            return None
        return get_email_status(self.team_id, message_id)

    def _report_status_read(self, request: Request, email_status: EmailStatus | None) -> None:
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly. That
        # user is not a Django User, so its distinct_id is read without a type.
        distinct_id = getattr(request.user, "distinct_id", None)
        if not isinstance(distinct_id, str):
            return
        try:
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event="transactional email api status read",
                properties={
                    "team_id": self.team_id,
                    "outcome": "not_found" if email_status is None else "found",
                    "status": email_status.status if email_status else None,
                    "auth_method": "project_secret_api_key",
                    "authorized_by": transactional_email_authorized_by(request, TRANSACTIONAL_EMAIL_STATUS_SCOPE),
                },
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email status read event", error=str(e))
