import json
import base64
import binascii
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ErrorDetail, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.enums import LabeledStrEnum
from posthog.event_usage import groups
from posthog.permissions import is_authenticated_via_project_secret_api_key

from products.messaging.backend.facade.transactional_email import (
    AlreadySending,
    DeliveryUnavailable,
    EmailCanceled,
    EmailNotFound,
    EmailSendStatus,
    EmailStatus,
    RescheduleTooFar,
    ScheduledEmailPage,
    TransactionalEmailError,
    cancel_email,
    get_email_status,
    list_scheduled_emails,
    reschedule_email,
)
from products.messaging.backend.presentation.views.code_send_fields import ScheduledAtField
from products.messaging.backend.presentation.views.refusals import ExplainedRefusal
from products.messaging.backend.presentation.views.transactional_email_access import (
    TRANSACTIONAL_EMAIL_SEND_SCOPE,
    TRANSACTIONAL_EMAIL_STATUS_SCOPE,
    lead_time_bucket,
    require_email_status_read,
    require_scheduled_sends,
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


class CanceledEmailSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The `message_id` of the canceled email.")
    status = serializers.CharField(help_text="Always `canceled`.")


class RescheduleEmailSerializer(serializers.Serializer):
    scheduled_at = ScheduledAtField(
        help_text="When to send the email instead, in ISO 8601 with a timezone offset, such as "
        "`2026-11-20T09:00:00Z` or `2026-11-20T10:00:00+01:00`, kept to the millisecond. At most 30 days after the "
        "email was sent. A time that already passed sends it now."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unknown = [name for name in self.initial_data if name not in self.fields]
        if unknown:
            raise serializers.ValidationError(
                {
                    unknown[0]: ErrorDetail(
                        "This route only moves an email, so it takes only `scheduled_at`. Send the email again to "
                        "change anything else.",
                        code="invalid_request",
                    )
                }
            )
        return attrs

    @property
    def partial(self) -> bool:
        return False

    @partial.setter
    def partial(self, value: bool) -> None:
        pass


class RescheduledEmailSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The `message_id` of the moved email.")
    status = serializers.CharField(
        help_text="Always `scheduled`. An email moved to now keeps this status until it goes out."
    )
    scheduled_at = serializers.DateTimeField(
        help_text="When the email goes out. For a time that already passed, this is the time of the move."
    )


class ListedEmailStatus(LabeledStrEnum):
    SCHEDULED = "scheduled", "Scheduled"


_EARLIEST_CLICKHOUSE_TIME = datetime(1900, 1, 1, tzinfo=UTC)
_LATEST_CLICKHOUSE_TIME_EXCLUSIVE = datetime(2300, 1, 1, tzinfo=UTC)


class ScheduledEmailListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ListedEmailStatus.choices,
        help_text="Which emails to list. Only `scheduled` is supported: the emails that wait for their time.",
    )
    cursor = serializers.CharField(
        required=False, help_text="The `next` value of the page before. Leave it out for the first page."
    )
    limit = serializers.IntegerField(
        required=False, default=100, min_value=1, max_value=100, help_text="How many emails a page holds, 1 to 100."
    )

    def validate_cursor(self, value: str) -> tuple[datetime, str]:
        try:
            due, message_id = json.loads(base64.urlsafe_b64decode(value.encode()))
            if not (isinstance(due, str) and isinstance(message_id, str)):
                raise ValueError
            due_at = datetime.fromisoformat(due)
            if due_at.tzinfo is None:
                raise ValueError
            due_at = due_at.astimezone(UTC)
            if not _EARLIEST_CLICKHOUSE_TIME <= due_at < _LATEST_CLICKHOUSE_TIME_EXCLUSIVE:
                raise ValueError
            return due_at, str(UUID(message_id))
        except (binascii.Error, UnicodeDecodeError, TypeError, ValueError, OverflowError):
            raise serializers.ValidationError("This cursor isn't one a page returned. Start again without it.")


class ScheduledEmailSerializer(serializers.Serializer):
    id = serializers.CharField(source="message_id", help_text="The `message_id` that the send returned.")
    to = serializers.CharField(help_text="The recipient's address.")
    scheduled_at = serializers.DateTimeField(help_text="When the email goes out, to the millisecond.")
    created_at = serializers.DateTimeField(help_text="When the send was made.")


@extend_schema_serializer(many=False)
class ScheduledEmailPageSerializer(serializers.Serializer):
    results = ScheduledEmailSerializer(many=True, help_text="The emails, soonest first.")
    next = serializers.CharField(
        allow_null=True, help_text="Pass this as `cursor` to read the next page. Null on the last page."
    )


def _cursor(page: ScheduledEmailPage) -> str | None:
    if page.next_after is None:
        return None
    due, message_id = page.next_after
    return base64.urlsafe_b64encode(json.dumps([due.isoformat(), message_id]).encode()).decode()


MANAGE_ACTIONS = ("cancel", "partial_update")
ALREADY_SENDING_RESPONSE = OpenApiResponse(
    description="PostHog has started sending this email, so it can't change. `code` is `already_sending`."
)
MANAGE_NOT_FOUND_RESPONSE = OpenApiResponse(
    description="No email of this project with this ID waits to go out: the ID is unknown, or the email went out a "
    "while ago."
)
MANAGE_UNAVAILABLE_RESPONSE = OpenApiResponse(
    description="The email pipeline didn't answer, so the email may not have changed. A retry is safe."
)


class _ScheduledSendsOff(serializers.ValidationError):
    pass


def _require_scheduled_moves(team: Any) -> None:
    try:
        require_scheduled_sends(
            team,
            "Scheduled sends aren't on for this project, so PostHog didn't move the email. Send a time that "
            "already passed to send it now.",
        )
    except serializers.ValidationError as e:
        raise _ScheduledSendsOff(e.detail) from None


class MessagingEmailsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["list", "retrieve", *MANAGE_ACTIONS]

    @property
    def required_scopes(self) -> list[str]:
        return [TRANSACTIONAL_EMAIL_SEND_SCOPE if self.action in MANAGE_ACTIONS else TRANSACTIONAL_EMAIL_STATUS_SCOPE]

    def get_throttles(self) -> list[BaseThrottle]:
        if not is_authenticated_via_project_secret_api_key(self.request):
            return super().get_throttles()
        return transactional_email_read_throttles()

    def handle_exception(self, exc: Exception) -> Response:
        response = super().handle_exception(exc)
        if isinstance(exc, ExplainedRefusal):
            exc.explain(response)
        return response

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
        _require_project_secret_api_key(request)
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

    @extend_schema(
        parameters=[ScheduledEmailListQuerySerializer],
        responses={
            200: ScheduledEmailPageSerializer,
            400: OpenApiResponse(description="`status` is missing or isn't `scheduled`, or the cursor isn't valid."),
            401: OpenApiResponse(description="The request has no project secret API key."),
        },
        summary="List scheduled emails",
        description=(
            "List the emails that wait for their time, soonest first, a page at a time. An email leaves the list "
            "when it goes out or is canceled. A new email, a cancel or a move can take up to a minute to show in "
            "the list. "
            "Needs a project secret API key with the `transactional_email:read` scope. A key with `hog_flow:read` "
            "also works, but that scope reaches the rest of Workflows too."
        ),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _require_project_secret_api_key(request)
        require_email_status_read(self.team)
        query = ScheduledEmailListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = list_scheduled_emails(
            self.team_id, after=query.validated_data.get("cursor"), limit=query.validated_data["limit"]
        )
        self._capture(
            request,
            "transactional email api manage",
            {
                "action": "list",
                "outcome": "listed",
                "authorized_by": transactional_email_authorized_by(request, TRANSACTIONAL_EMAIL_STATUS_SCOPE),
            },
        )
        return Response(ScheduledEmailPageSerializer({"results": page.results, "next": _cursor(page)}).data)

    @extend_schema(
        request=None,
        parameters=[MESSAGE_ID_PARAMETER],
        responses={
            200: CanceledEmailSerializer,
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: MANAGE_NOT_FOUND_RESPONSE,
            409: ALREADY_SENDING_RESPONSE,
            503: MANAGE_UNAVAILABLE_RESPONSE,
        },
        summary="Cancel a scheduled email",
        description=(
            "Cancel an email before PostHog starts sending it, by the `message_id` that the send returned. A repeat "
            "cancel answers 200 too. Needs a project secret API key with the `transactional_email:write` scope. A key "
            "with `hog_flow:write` also works, but that scope reaches the rest of Workflows too."
        ),
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        _require_project_secret_api_key(request)
        require_email_status_read(self.team)
        with self._reporting_manage(request, "cancel") as report:
            message_id = _message_id(pk)
            cancel_email(self.team_id, message_id)
            report["outcome"] = "canceled"
        return Response(CanceledEmailSerializer({"id": str(message_id), "status": EmailSendStatus.CANCELED}).data)

    @extend_schema(
        request=RescheduleEmailSerializer,
        parameters=[MESSAGE_ID_PARAMETER],
        responses={
            200: RescheduledEmailSerializer,
            400: OpenApiResponse(
                description="`scheduled_at` is missing, has no timezone offset, or is more than 30 days after the "
                "email was sent; the body has a field other than `scheduled_at`; or scheduled sends aren't on for "
                "this project and the time is in the future."
            ),
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: MANAGE_NOT_FOUND_RESPONSE,
            409: OpenApiResponse(
                description="The email can't move. `code` is `already_sending` when PostHog has started sending it, "
                "and `canceled` when it was canceled."
            ),
            503: MANAGE_UNAVAILABLE_RESPONSE,
        },
        summary="Move a scheduled email",
        description=(
            "Change when an email goes out, before PostHog starts sending it, by the `message_id` that the send "
            "returned. A time that already passed sends it now. Needs a project secret API key with the "
            "`transactional_email:write` scope. A key with `hog_flow:write` also works, but that scope reaches the "
            "rest of Workflows too."
        ),
    )
    def partial_update(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        _require_project_secret_api_key(request)
        require_email_status_read(self.team)
        with self._reporting_manage(request, "reschedule") as report:
            serializer = RescheduleEmailSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            requested_at = serializer.validated_data["scheduled_at"]
            report["lead_time_bucket"] = lead_time_bucket(requested_at)
            if report["lead_time_bucket"] != "now":
                _require_scheduled_moves(self.team)
            message_id = _message_id(pk)
            scheduled_at = reschedule_email(self.team_id, message_id, requested_at)
            report["outcome"] = "scheduled"
        return Response(
            RescheduledEmailSerializer(
                {"id": str(message_id), "status": EmailSendStatus.SCHEDULED, "scheduled_at": scheduled_at}
            ).data
        )

    @contextmanager
    def _reporting_manage(self, request: Request, action: str) -> Iterator[dict[str, Any]]:
        report: dict[str, Any] = {"outcome": "error"}
        try:
            yield report
        except _ScheduledSendsOff:
            report["outcome"] = "scheduled_sends_off"
            raise
        except serializers.ValidationError:
            report["outcome"] = "invalid_request"
            raise
        except EmailNotFound:
            report["outcome"] = "not_found"
            raise NotFound() from None
        except EmailCanceled as e:
            report["outcome"] = "canceled_before"
            raise _explained(e, "This email was canceled, so PostHog didn't move it.") from None
        except AlreadySending as e:
            report["outcome"] = "already_sending"
            verb = "canceled" if action == "cancel" else "moved"
            raise _explained(e, f"PostHog has started sending this email, so it can't be {verb}.") from None
        except RescheduleTooFar as e:
            report["outcome"] = "invalid_scheduled_at"
            raise _explained(e, str(e), status_code=status.HTTP_400_BAD_REQUEST) from None
        except DeliveryUnavailable:
            report["outcome"] = "unavailable"
            raise ExplainedRefusal(
                "The email pipeline didn't answer, so the email may not have changed.",
                code="delivery_unavailable",
                why="PostHog couldn't reach the service that holds the email.",
                fix="Try again shortly. A retry is safe.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from None
        finally:
            self._capture(
                request,
                "transactional email api manage",
                {
                    "action": action,
                    **report,
                    "authorized_by": transactional_email_authorized_by(request, TRANSACTIONAL_EMAIL_SEND_SCOPE),
                },
            )

    def _report_status_read(self, request: Request, email_status: EmailStatus | None) -> None:
        self._capture(
            request,
            "transactional email api status read",
            {
                "outcome": "not_found" if email_status is None else "found",
                "status": email_status.status if email_status else None,
                "authorized_by": transactional_email_authorized_by(request, TRANSACTIONAL_EMAIL_STATUS_SCOPE),
            },
        )

    def _capture(self, request: Request, event: str, properties: dict[str, Any]) -> None:
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly. That
        # user is not a Django User, so its distinct_id is read without a type.
        distinct_id = getattr(request.user, "distinct_id", None)
        if not isinstance(distinct_id, str):
            return
        try:
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event=event,
                properties={
                    "team_id": self.team_id,
                    **properties,
                    "auth_method": "project_secret_api_key",
                },
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email event", analytics_event=event, error=str(e))


def _require_project_secret_api_key(request: Request) -> None:
    if not is_authenticated_via_project_secret_api_key(request):
        raise exceptions.NotAuthenticated()


def _message_id(pk: str | None) -> UUID:
    try:
        return UUID(str(pk))
    except ValueError:
        raise EmailNotFound() from None


def _explained(
    error: TransactionalEmailError, detail: str, *, status_code: int = status.HTTP_409_CONFLICT
) -> ExplainedRefusal:
    return ExplainedRefusal(
        detail,
        code=error.code,
        attr=error.attr,
        why=getattr(error, "why", ""),
        fix=getattr(error, "fix", ""),
        status_code=status_code,
    )
