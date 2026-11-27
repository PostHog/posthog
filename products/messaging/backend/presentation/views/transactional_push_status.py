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

from products.messaging.backend.facade.contracts import PushSendStatus, PushStatusReason, TransactionalPushStatus
from products.messaging.backend.facade.transactional_email import is_idempotency_key
from products.messaging.backend.facade.transactional_push_log import get_push_status, keyed_push_run_id
from products.messaging.backend.presentation.query_concurrency import query_concurrency_slots
from products.messaging.backend.presentation.views.message_templates import (
    TRANSACTIONAL_PUSH_STATUS_SCOPE,
    legacy_scope_object_used,
    require_transactional_push_api,
)

logger = structlog.get_logger(__name__)

MESSAGE_ID_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="The `message_id` that the send returned.",
)


class PushStatusSerializer(serializers.Serializer):
    id = serializers.CharField(source="run_id", help_text="The `message_id` that the send returned.")
    status = serializers.ChoiceField(
        choices=PushSendStatus.choices,
        help_text="What happened to the push notification. `sending` means it is still going out, or that it finished in the "
        "last minute and PostHog hasn't recorded its outcome yet. `sent` means Apple "
        "or Google accepted it for at least one of the person's devices. `not_sent` means none of the person's "
        "devices got it, and `reason` says why. `failed` means the send stopped with an error.",
    )
    created_at = serializers.DateTimeField(help_text="When PostHog accepted the send.")
    reason = serializers.ChoiceField(
        choices=PushStatusReason.choices,
        allow_null=True,
        help_text="Why a push notification was not sent or failed. A not sent push has `no_person` when no person "
        "has the `distinct_id`, `no_device` when the person has no registered device for the template's channels or "
        "every device token expired, `opted_out` or `frequency_capped`, or `unknown`. A failed push has "
        "`integration_error` when the Firebase or APNs integration is missing or needs reconnecting, "
        "`provider_error` when Apple or Google refused it, `canceled`, or `error`. Null while it is sending and once "
        "it was sent.",
    )


class PushStatusLookupSerializer(serializers.Serializer):
    message_id = serializers.UUIDField(required=False, help_text="The `message_id` that the send returned.")
    idempotency_key = serializers.CharField(
        required=False,
        trim_whitespace=False,
        help_text="The `Idempotency-Key` the send was made with, when you don't have its `message_id`, for example "
        "after a lost response.",
    )

    def validate_idempotency_key(self, value: str) -> str:
        if not is_idempotency_key(value):
            raise serializers.ValidationError("Use 1 to 255 visible ASCII characters, with no spaces.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        named = [name for name in ("message_id", "idempotency_key") if name in self.initial_data]
        if len(named) != 1 or named[0] not in attrs:
            raise serializers.ValidationError(
                "Name the push notification with either `message_id` or `idempotency_key`."
            )
        if len(self.initial_data.getlist(named[0])) > 1:
            raise serializers.ValidationError(f"Name the push notification with one `{named[0]}`.")
        return attrs


# Reads have their own buckets, so polling for status can't use up the send budget.
class TransactionalPushReadBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_push_read_burst"
    rate = "600/minute"


class TransactionalPushReadSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_push_read_sustained"
    rate = "20000/hour"


class TransactionalPushReadTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_push_read_psak_team_burst"
    rate = "600/minute"


class TransactionalPushReadTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_push_read_psak_team_sustained"
    rate = "20000/hour"


class MessagingPushesViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    required_scopes = [TRANSACTIONAL_PUSH_STATUS_SCOPE]
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["retrieve", "lookup"]

    def get_throttles(self) -> list[BaseThrottle]:
        # Only a project secret API key can read, and the push read buckets count those. Any other caller gets the
        # default API throttles on its way to a 401.
        if not is_authenticated_via_project_secret_api_key(self.request):
            return super().get_throttles()
        return [
            TransactionalPushReadBurstThrottle(),
            TransactionalPushReadSustainedThrottle(),
            TransactionalPushReadTeamBurstThrottle(),
            TransactionalPushReadTeamSustainedThrottle(),
        ]

    @extend_schema(
        parameters=[MESSAGE_ID_PARAMETER],
        responses={
            200: PushStatusSerializer,
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: OpenApiResponse(
                description="No push notification of this project has this ID, or it is older than 30 days. In the "
                "first seconds after a send, it means PostHog accepted the push but hasn't recorded it yet."
            ),
        },
        summary="Get a transactional push notification's status",
        description=(
            "Get the status of one transactional push notification by the `message_id` that the send returned, "
            "for 30 days after the send. Needs a project secret API key with the `transactional_push:read` scope. A "
            "key with `hog_flow:read` also works, but that scope reaches the rest of Workflows too. The send is "
            "recorded a few seconds after it is accepted, so a read right after a send can answer 404. Read again a "
            "few seconds later."
        ),
    )
    def retrieve(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        # The routing mixin adds session and personal API key authentication to every route. A status is read by the
        # server that sent the push, so only its project secret API key can read it.
        if not is_authenticated_via_project_secret_api_key(request):
            raise exceptions.NotAuthenticated()
        require_transactional_push_api(self.team)
        try:
            run_id = UUID(str(pk))
        except ValueError:
            run_id = None
        if run_id is None:
            return self._respond(request, None)
        with query_concurrency_slots(self.team):
            push_status = get_push_status(self.team_id, run_id)
        return self._respond(request, push_status)

    @extend_schema(
        parameters=[PushStatusLookupSerializer],
        responses={
            200: PushStatusSerializer,
            400: OpenApiResponse(
                description="The request names neither or both of `message_id` and `idempotency_key`, names one "
                "of them twice, or gives one in the wrong format: an `message_id` that isn't a UUID, or an "
                "`idempotency_key` that isn't 1 to 255 visible ASCII characters."
            ),
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: OpenApiResponse(
                description="No push notification of this project has this ID or key, or it is older than 30 days. "
                "In the first seconds after a send, it means PostHog accepted the push but hasn't recorded it yet."
            ),
        },
        summary="Find a transactional push notification's status",
        description=(
            "Get the status of one transactional push notification by its `message_id`, or by the "
            "`Idempotency-Key` it was sent with when the send's response was lost. Name exactly one of them. It "
            "answers like the read by `message_id`, for 30 days after the send, and needs the same "
            "`transactional_push:read` scope. A 404 doesn't mean the push wasn't sent: it can take a few seconds to "
            "be recorded."
        ),
    )
    @action(detail=False, methods=["GET"], url_path="status")
    def lookup(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not is_authenticated_via_project_secret_api_key(request):
            raise exceptions.NotAuthenticated()
        require_transactional_push_api(self.team)
        lookup = PushStatusLookupSerializer(data=request.query_params)
        lookup.is_valid(raise_exception=True)
        run_id = lookup.validated_data.get("message_id") or keyed_push_run_id(
            self.team_id, lookup.validated_data["idempotency_key"]
        )
        with query_concurrency_slots(self.team):
            push_status = get_push_status(self.team_id, run_id)
        return self._respond(request, push_status)

    def _respond(self, request: Request, push_status: TransactionalPushStatus | None) -> Response:
        self._report_status_read(request, push_status)
        if push_status is None:
            raise NotFound()
        return Response(PushStatusSerializer(push_status).data)

    def _report_status_read(self, request: Request, push_status: TransactionalPushStatus | None) -> None:
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly. That
        # user is not a Django User, so its distinct_id is read without a type.
        distinct_id = getattr(request.user, "distinct_id", None)
        if not isinstance(distinct_id, str):
            return
        try:
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event="transactional push api status read",
                properties={
                    "team_id": self.team_id,
                    "outcome": "not_found" if push_status is None else "found",
                    "status": push_status.status.value if push_status else None,
                    "reason": push_status.reason.value if push_status and push_status.reason else None,
                    "auth_method": "project_secret_api_key",
                    "authorized_by": legacy_scope_object_used(request, TRANSACTIONAL_PUSH_STATUS_SCOPE)
                    or "transactional_push",
                },
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional push status read event", error=str(e))
