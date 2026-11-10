import uuid
from typing import Any, cast

from django.db import models

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser
from posthog.redis import get_client

from products.signals.backend.facade.api import (
    MAX_RUN_NOTE_CHARS,
    ScoutRunRejectionKind,
    WorkflowScoutRunQueued,
    WorkflowScoutRunRejected,
    start_workflow_scout_run,
)
from products.workflows.backend.facade.api import workflow_exists
from products.workflows.backend.facade.service_jwt import WORKFLOW_SCOUT_RUN_PURPOSE
from products.workflows.backend.presentation.views.workflow_step_auth import WorkflowStepJWTAuthentication

logger = structlog.get_logger(__name__)

# Covers the whole retry window a staged fetch can span: the JWT that carries idempotency_key
# lives 30 minutes (nodejs/src/cdp/async-functions/run-scout.ts), and this outlives that with
# margin for engine backoff and queue lag. Temporal's own id-conflict policy only dedupes a
# retry that lands while the original run is still open (ALLOW_DUPLICATE lets a closed run's id
# be reused for a fresh, billable execution) — this cache is what catches a retry landing after
# the original run has already finished.
IDEMPOTENCY_KEY_TTL_SECONDS = 60 * 60


def _idempotency_cache_key(hog_flow_id: uuid.UUID, idempotency_key: str) -> str:
    # Scoped by workflow so one workflow's key can never replay another's dispatch.
    return f"workflow_scout_run_idempotency:{hog_flow_id}:{idempotency_key}"


# Cached under an idempotency key in place of a workflow id when the fire was queued. A workflow id
# never takes this value, so a replay can tell the two apart.
_QUEUED_CACHE_VALUE = "queued"


# The step only treats 409 as a graceful skip, so every backpressure kind (paused, cooldown,
# budget, quota, run in flight) maps onto it; a scout that cannot run at all fails the step so the
# author notices. A busy scout queues the fire instead, unless the step asked to skip it.
_REJECTION_STATUS: dict[ScoutRunRejectionKind, int] = {
    ScoutRunRejectionKind.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScoutRunRejectionKind.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ScoutRunRejectionKind.CONFLICT: status.HTTP_409_CONFLICT,
    ScoutRunRejectionKind.THROTTLED: status.HTTP_409_CONFLICT,
}


class WorkflowScoutRunsJWTAuthentication(WorkflowStepJWTAuthentication):
    purpose = WORKFLOW_SCOUT_RUN_PURPOSE


class WorkflowScoutRunWhenBusy(models.TextChoices):
    QUEUE = "queue", "Queue the trigger"
    SKIP = "skip", "Skip it"


class WorkflowScoutRunCreateSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        max_length=200, help_text="Name of the scout to run, for example signals-scout-error-tracking."
    )
    idempotency_key = serializers.CharField(
        max_length=128,
        required=False,
        help_text="Stable key for this invocation. A retried request with the same key returns the run it dispatched, without spending another.",
    )
    note = serializers.CharField(
        max_length=MAX_RUN_NOTE_CHARS,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text=(
            "Optional note for this run alone, rendered by the step from its triggering event, for example "
            "'PR #123'. The scout handles what the note names before anything else, and reads it as untrusted "
            "input. Blank means no note."
        ),
    )
    when_busy = serializers.ChoiceField(
        choices=WorkflowScoutRunWhenBusy.choices,
        required=False,
        default=WorkflowScoutRunWhenBusy.QUEUE,
        help_text=(
            "What happens when the scout is busy, which means it ran from a workflow in the last 30 minutes or one "
            "of its runs is in progress. 'queue' keeps the trigger, and a later run handles its note. 'skip' drops "
            "the trigger and answers 409."
        ),
    )


class WorkflowScoutRunResponseSerializer(serializers.Serializer):
    scout = serializers.CharField(help_text="The scout that was run, or that will handle the queued trigger.")
    workflow_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Temporal workflow ID of the dispatched scout run. Null when the trigger was queued.",
    )
    queued = serializers.BooleanField(
        default=False,
        help_text="True when the scout was busy and the trigger waits for a later run. No run has started for it yet.",
    )


class WorkflowScoutRunRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the scout was not run.")


class WorkflowScoutRunViewSet(viewsets.GenericViewSet):
    """Start a Signals scout run from a workflow's "Run scout" action. Authenticated by a scoped
    service JWT minted by the plugin server, never by a user credential, with its own signing key
    and audience.

    The only content from the triggering event that reaches the scout is the step's optional
    `note`, which the scout reads as untrusted input naming the subject it handles first. Without
    one, the scout is told a workflow started it and otherwise runs as it does on its schedule. A
    run never stamps the scout's last_run_at and never feeds
    its failure-streak breaker — a workflow trigger is additive to the schedule, not a
    substitute for it.

    A fire that arrives while the scout is busy is queued, and a later run handles its note,
    unless the step's `when_busy` asks to skip it."""

    authentication_classes = [WorkflowScoutRunsJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowScoutRunCreateSerializer

    @extend_schema(
        request=WorkflowScoutRunCreateSerializer,
        responses={
            202: OpenApiResponse(
                response=WorkflowScoutRunResponseSerializer,
                description=(
                    "The scout run was dispatched, or the scout was busy and the trigger was queued for a later run. "
                    "A dispatched run runs asynchronously; poll the scout's runs for the result"
                ),
            ),
            403: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow lives in a child environment, which cannot run scouts",
            ),
            404: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="No runnable scout of that name exists in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description=(
                    "The scout is paused or over its daily budget or quota, or it is busy and the step asked to skip"
                ),
            ),
            422: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow no longer exists",
            ),
        },
        summary="Run a Signals scout from a workflow",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both from the verified token, not the URL or body.
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        serializer = WorkflowScoutRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        skill_name = serializer.validated_data["skill_name"].strip()
        idempotency_key = serializer.validated_data.get("idempotency_key")
        note = serializer.validated_data.get("note") or None
        cache_key = _idempotency_cache_key(hog_flow_id, idempotency_key) if idempotency_key else None

        # A replay of an already-dispatched key returns that run before any other check, same as
        # the task-creation endpoint's origin_key — no need to re-resolve the workflow or re-run
        # the scout's gates for a request this key has already spent.
        if cache_key is not None:
            cached = get_client().get(cache_key)
            if cached is not None:
                cached_value = cached.decode() if isinstance(cached, bytes) else cached
                if cached_value == _QUEUED_CACHE_VALUE:
                    return _queued(skill_name)
                return _dispatched(skill_name, cached_value)

        # A token outlives the workflow it was minted for (its TTL covers the whole fetch retry
        # chain), so a deleted workflow must not still be able to spend scout runs.
        if not workflow_exists(team_id=team_id, workflow_id=hog_flow_id):
            return _rejected("Workflow no longer exists.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            outcome = start_workflow_scout_run(
                team_id=team_id,
                skill_name=skill_name,
                workflow_origin_key=idempotency_key,
                run_note=note,
                trigger_workflow_id=str(hog_flow_id),
                queue_when_busy=serializer.validated_data["when_busy"] == WorkflowScoutRunWhenBusy.QUEUE,
            )
        except WorkflowScoutRunRejected as error:
            logger.info(
                "workflow_scout_run_rejected",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                skill_name=skill_name,
                reason=error.rejection.reason,
            )
            return _rejected(error.rejection.detail, _REJECTION_STATUS[error.rejection.kind])

        if isinstance(outcome, WorkflowScoutRunQueued):
            logger.info(
                "workflow_scout_run_queued",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                skill_name=outcome.skill_name,
                pending_count=outcome.pending_count,
            )
            if cache_key is not None:
                get_client().set(cache_key, _QUEUED_CACHE_VALUE, ex=IDEMPOTENCY_KEY_TTL_SECONDS)
            return _queued(outcome.skill_name)

        logger.info(
            "workflow_scout_run_started",
            team_id=team_id,
            hog_flow_id=str(hog_flow_id),
            skill_name=outcome.skill_name,
            workflow_id=outcome.workflow_id,
        )
        if cache_key is not None:
            get_client().set(cache_key, outcome.workflow_id, ex=IDEMPOTENCY_KEY_TTL_SECONDS)
        return _dispatched(outcome.skill_name, outcome.workflow_id)


def _dispatched(skill_name: str, workflow_id: str) -> Response:
    return Response(
        WorkflowScoutRunResponseSerializer({"scout": skill_name, "workflow_id": workflow_id}).data,
        status=status.HTTP_202_ACCEPTED,
    )


def _queued(skill_name: str) -> Response:
    return Response(
        WorkflowScoutRunResponseSerializer({"scout": skill_name, "workflow_id": None, "queued": True}).data,
        status=status.HTTP_202_ACCEPTED,
    )


def _rejected(detail: str, http_status: int) -> Response:
    return Response(WorkflowScoutRunRejectedSerializer({"detail": detail}).data, status=http_status)
