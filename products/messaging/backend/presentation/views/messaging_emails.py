from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.dataclasses import frozen
from posthog.permissions import is_authenticated_via_project_secret_api_key

from products.messaging.backend.facade.email_status import (
    EMAIL_STATUS_RETENTION,
    EmailStatus,
    EmailStatusRecord,
    get_email_status,
    list_email_statuses_by_recipient,
    message_created_at,
)
from products.messaging.backend.presentation.views.transactional_email_api import (
    TemplateErrorSerializer,
    TemplateRefusal,
    TransactionalEmailBurstThrottle,
    TransactionalEmailSustainedThrottle,
    TransactionalEmailTeamBurstThrottle,
    TransactionalEmailTeamSustainedThrottle,
    TransactionalEmailViewSetMixin,
    invalid_request,
)


# The send's rates under their own scopes, so polling a status never uses up the budget for sending.
class EmailStatusBurstThrottle(TransactionalEmailBurstThrottle):
    scope = "transactional_email_read_burst"


class EmailStatusSustainedThrottle(TransactionalEmailSustainedThrottle):
    scope = "transactional_email_read_sustained"


class EmailStatusTeamBurstThrottle(TransactionalEmailTeamBurstThrottle):
    scope = "transactional_email_read_psak_team_burst"


class EmailStatusTeamSustainedThrottle(TransactionalEmailTeamSustainedThrottle):
    scope = "transactional_email_read_psak_team_sustained"


LOOKUP_PAGE_SIZE = 50
LOOKUP_MAX_PAGE_SIZE = 100
CURSOR_NOT_FROM_A_PAGE = "This cursor did not come from a previous page of this lookup."


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


class EmailLookupSerializer(serializers.Serializer):
    to = serializers.EmailField(
        help_text="The recipient's address. Case and the spaces around it do not matter. A send's `cc` and `bcc` "
        "copies are not looked up.",
    )
    limit = serializers.IntegerField(
        min_value=1,
        max_value=LOOKUP_MAX_PAGE_SIZE,
        default=LOOKUP_PAGE_SIZE,
        help_text=f"How many emails a page holds, from 1 to {LOOKUP_MAX_PAGE_SIZE}.",
    )
    cursor = serializers.UUIDField(
        required=False,
        error_messages={"invalid": CURSOR_NOT_FROM_A_PAGE},
        help_text="The `next_cursor` of the previous page. Leave it out to read the first page.",
    )

    def validate_cursor(self, cursor: UUID) -> UUID:
        if message_created_at(cursor) is None:
            raise serializers.ValidationError(CURSOR_NOT_FROM_A_PAGE)
        return cursor


# drf-spectacular types a `list` action's response as an array unless told it is one page object.
@extend_schema_serializer(many=False)
class EmailStatusPageSerializer(serializers.Serializer):
    results = EmailStatusSerializer(many=True, help_text="The recipient's emails, newest first.")
    next_cursor = serializers.UUIDField(
        allow_null=True,
        help_text="Pass this as `cursor` to read the next page. Null on the last page.",
    )


def invalid_lookup(errors: Any) -> TemplateRefusal:
    return invalid_request(
        errors,
        why=f"A lookup needs the recipient's address, a page size from 1 to {LOOKUP_MAX_PAGE_SIZE}, and a cursor "
        "only from a previous page.",
        retry="look up again",
    )


@frozen
class EmailStatusPage:
    results: list[EmailStatusRecord]
    next_cursor: UUID | None


def recipient_email_page(team_id: int, to: str, limit: int, cursor: UUID | None = None) -> EmailStatusPage:
    # One extra row tells whether a next page exists without a second query.
    records = list_email_statuses_by_recipient(
        team_id, to, since=datetime.now(UTC) - EMAIL_STATUS_RETENTION, limit=limit + 1, cursor=cursor
    )
    page = records[:limit]
    return EmailStatusPage(results=page, next_cursor=page[-1].message_id if len(records) > limit else None)


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
    psak_allowed_actions = ["list", "retrieve"]
    throttle_classes = [
        EmailStatusBurstThrottle,
        EmailStatusSustainedThrottle,
        EmailStatusTeamBurstThrottle,
        EmailStatusTeamSustainedThrottle,
    ]

    def _require_project_secret_api_key(self) -> None:
        # The routing mixin adds user credentials to every route. A status row names no workflow, so a user's
        # workflow access cannot limit what they read here.
        if not is_authenticated_via_project_secret_api_key(self.request):
            raise exceptions.NotAuthenticated()

    @extend_schema(
        parameters=[EmailLookupSerializer],
        responses={
            200: OpenApiResponse(response=EmailStatusPageSerializer, description="A page of the recipient's emails"),
            400: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="The address, the page size or the cursor is not valid",
            ),
            429: OpenApiResponse(response=TemplateErrorSerializer, description="Rate limited, retry later"),
        },
        summary="List a recipient's transactional emails",
        description="Read the status of each email sent to an address in the last 30 days, newest first. Use it when "
        "you did not keep the `message_id` a send answered.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()
        self._require_project_secret_api_key()
        lookup = EmailLookupSerializer(data=request.query_params)
        if not lookup.is_valid():
            return Response(
                TemplateErrorSerializer(invalid_lookup(lookup.errors)).data, status=status.HTTP_400_BAD_REQUEST
            )
        page = recipient_email_page(self.team_id, **lookup.validated_data)
        return Response(EmailStatusPageSerializer(page).data)

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
        self._require_project_secret_api_key()
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
