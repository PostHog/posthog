from typing import Any
from uuid import UUID

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.event_usage import groups
from posthog.permissions import is_authenticated_via_project_secret_api_key
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.messaging.backend.facade.transactional_email import (
    EmailSendStatus,
    EmailStatus,
    get_email_status,
    is_idempotency_key,
    keyed_message_id,
)
from products.messaging.backend.presentation.views.message_templates import (
    TRANSACTIONAL_EMAIL_STATUS_SCOPE,
    require_email_status_read,
    transactional_email_authorized_by,
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
        help_text="What happened to the email. `scheduled` means it waits for the time it was scheduled for. "
        "`queued` means it waits to go out. `sent` means PostHog handed it to the email provider. `failed` means it "
        "was not sent, and `reason` says why. A rerun of the send can still move it to `sent`. `delivered` means the "
        "recipient's mail server accepted it. `bounced` and `complained` come later from the recipient's mail provider.",
    )
    created_at = serializers.DateTimeField(help_text="When PostHog accepted the send.")
    status_at = serializers.DateTimeField(help_text="When the email reached its current status.")
    reason = serializers.CharField(
        allow_null=True,
        help_text="Why a failed email was not sent, or the bounce type of a bounced email. A failed send has "
        "`provider_error`, or `provider_rejected` when the provider refused the email after it accepted the send. A skipped send has `recipient_suppressed`, `recipient_unreachable`, `recipient_opted_out`, "
        "`missing_recipient`, `sending_paused`, `sending_suspended` or `frequency_capped`. A run that stopped before "
        "the send has `canceled`, `workflow_unavailable` or an error kind such as `timeout`, and more error kinds can "
        "be added. A bounce has `hard`, `soft` or `unknown`. Null otherwise.",
    )


class EmailStatusLookupSerializer(serializers.Serializer):
    message_id = serializers.UUIDField(required=False, help_text="The `message_id` that the send returned.")
    idempotency_key = serializers.CharField(
        required=False,
        trim_whitespace=False,
        help_text="The `idempotency_key` the send was made with, when you don't have its `message_id`, for example "
        "after a lost response.",
    )

    def validate_idempotency_key(self, value: str) -> str:
        if not is_idempotency_key(value):
            raise serializers.ValidationError("Use 1 to 255 visible ASCII characters, with no spaces.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        named = [name for name in ("message_id", "idempotency_key") if name in self.initial_data]
        if len(named) != 1 or named[0] not in attrs:
            raise serializers.ValidationError("Name the email with either `message_id` or `idempotency_key`.")
        if len(self.initial_data.getlist(named[0])) > 1:
            raise serializers.ValidationError(f"Name the email with one `{named[0]}`.")
        return attrs


# Reads have their own buckets, so polling for status can't use up the send budget.
class TransactionalEmailReadBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_read_burst"
    rate = "600/minute"


class TransactionalEmailReadSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_read_sustained"
    rate = "20000/hour"


class TransactionalEmailReadTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_read_psak_team_burst"
    rate = "600/minute"


class TransactionalEmailReadTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_read_psak_team_sustained"
    rate = "20000/hour"


class MessagingEmailsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    required_scopes = [TRANSACTIONAL_EMAIL_STATUS_SCOPE]
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["retrieve", "lookup"]

    def get_throttles(self) -> list[BaseThrottle]:
        # Only a project secret API key can read, and the email read buckets count those. Any other caller gets the
        # default API throttles on its way to a 401.
        if not is_authenticated_via_project_secret_api_key(self.request):
            return super().get_throttles()
        return [
            TransactionalEmailReadBurstThrottle(),
            TransactionalEmailReadSustainedThrottle(),
            TransactionalEmailReadTeamBurstThrottle(),
            TransactionalEmailReadTeamSustainedThrottle(),
        ]

    @extend_schema(
        parameters=[MESSAGE_ID_PARAMETER],
        responses={
            200: EmailStatusSerializer,
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: OpenApiResponse(
                description="No email of this project has this ID, or it is older than 30 days. In the first "
                "seconds after a send, it means PostHog accepted the email but hasn't recorded its first status yet."
            ),
        },
        summary="Get a transactional email's status",
        description=(
            "Get the status of one transactional email by the `message_id` that the send returned, for 30 days after "
            "the send. Needs a project secret API key with the `transactional_email:read` scope. A key with "
            "`hog_flow:read` also works, but that scope reaches the rest of Workflows too. The first status is "
            "recorded a few seconds after the send, so a read right after a send can answer 404. That 404 doesn't say "
            "whether the email went out yet, so read again a few seconds later."
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

    @extend_schema(
        parameters=[EmailStatusLookupSerializer],
        responses={
            200: EmailStatusSerializer,
            400: OpenApiResponse(
                description="The request names neither or both of `message_id` and `idempotency_key`, names one of "
                "them twice, or gives one in the wrong format: a `message_id` that isn't a UUID, or an "
                "`idempotency_key` that isn't 1 to 255 visible ASCII characters."
            ),
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: OpenApiResponse(
                description="No email of this project has this ID or key, or it is older than 30 days. In the first "
                "seconds after a send, it means PostHog accepted the email but hasn't recorded its first status yet."
            ),
        },
        summary="Find a transactional email's status",
        description=(
            "Get the status of one transactional email by its `message_id`, or by the `idempotency_key` it was sent "
            "with when the send's response was lost. Name exactly one of them. A key gives the latest send with it "
            "that PostHog has a status for. Compare the response's `created_at` with when you sent: an earlier time "
            "means an earlier send with the same key, not the one whose response was lost. It answers like the read "
            "by `message_id`, for 30 days after the send, and needs the same `transactional_email:read` scope. A 404 "
            "doesn't mean the email wasn't sent: its first status can take a few seconds to arrive. To make sure it "
            "goes out, send it again with the same key within 24 hours."
        ),
    )
    @action(detail=False, methods=["GET"], url_path="status")
    def lookup(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not is_authenticated_via_project_secret_api_key(request):
            raise exceptions.NotAuthenticated()
        require_email_status_read(self.team)
        lookup = EmailStatusLookupSerializer(data=request.query_params)
        lookup.is_valid(raise_exception=True)
        message_id = lookup.validated_data.get("message_id") or keyed_message_id(
            self.team_id, lookup.validated_data["idempotency_key"]
        )
        email_status = get_email_status(self.team_id, message_id)
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
