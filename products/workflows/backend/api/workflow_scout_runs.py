import uuid
from typing import Any, cast

from django.core.cache import cache

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.cdp.flag_gated_templates import FLAG_GATED_TEMPLATE_IDS, gated_template_enabled
from posthog.models import Team

from products.signals.backend.facade.api import (
    ScoutRunRejectionKind,
    WorkflowScoutRunRejected,
    WorkflowScoutRunStarted,
    start_workflow_scout_run,
)
from products.workflows.backend.api.run_scout_validation import RUN_SCOUT_TEMPLATE_ID
from products.workflows.backend.models import HogFlow
from products.workflows.backend.service_jwt import SIGNALS_SCOUT_RUN_PURPOSE

logger = structlog.get_logger(__name__)

# How long a dispatched fire stays answerable by its idempotency key. The workflow engine re-sends
# the identical request when a 202 is lost (a client-side timeout on a slow dispatch, most
# likely), and every retry has to read as the same success rather than a 409 from its own run.
# Sized to the step token's lifetime, which already bounds the whole fetch retry chain.
_REPLAY_TTL_S = 30 * 60

# Placeholder a request claims its key with before dispatching, so a retry that overlaps it can
# tell "my earlier attempt is mid-dispatch" from "nothing has run for this key".
_PENDING = {"pending": True}

# How a Signals rejection is surfaced. 409 and 429 are declared non-failure statuses on the
# template, so the workflow step reads them as a graceful skip; everything else fails the step,
# which is what a node pointing at a scout that cannot run should do.
_REJECTION_STATUS: dict[ScoutRunRejectionKind, int] = {
    ScoutRunRejectionKind.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScoutRunRejectionKind.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ScoutRunRejectionKind.CONFLICT: status.HTTP_409_CONFLICT,
    ScoutRunRejectionKind.THROTTLED: status.HTTP_429_TOO_MANY_REQUESTS,
}


class WorkflowScoutRunJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = SIGNALS_SCOUT_RUN_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # The workflow is identified by the verified token, never by the request body, so a token
        # minted for one workflow can't start runs attributed to another.
        try:
            hog_flow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, hog_flow_id


class WorkflowScoutRunCreateSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        max_length=200, help_text="Name of the scout to run, as shown in the project's scout fleet."
    )
    # Wide enough for the engine's `<invocation uuid>:<action id>` key at the action id's own
    # 200-character limit; a valid step must never 400 here.
    idempotency_key = serializers.CharField(
        max_length=256,
        required=False,
        help_text=(
            "Stable key for this workflow step. A retry carrying the key of a fire that already "
            "dispatched a run gets that fire's 202 back instead of a conflict."
        ),
    )


class WorkflowScoutRunResponseSerializer(serializers.Serializer):
    skill_name = serializers.CharField(help_text="The scout that was run.")
    workflow_id = serializers.CharField(help_text="Temporal workflow id of the dispatched run.")
    started = serializers.BooleanField(help_text="Always true; a rejected fire is a 4xx instead.")


class WorkflowScoutRunRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the run was not started.")


class WorkflowScoutRunViewSet(viewsets.GenericViewSet):
    """Start Signals scout runs from a workflow's "Run scout" action. Authenticated by a scoped
    service JWT minted by the plugin server, never by a user credential.

    The run is a pure kick: nothing from the triggering event is forwarded, so the scout explores
    exactly as it would on its schedule."""

    authentication_classes = [WorkflowScoutRunJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowScoutRunCreateSerializer

    @extend_schema(
        request=WorkflowScoutRunCreateSerializer,
        responses={
            202: OpenApiResponse(
                response=WorkflowScoutRunResponseSerializer,
                description="A run was dispatched. It executes asynchronously; poll the scout's runs for the result.",
            ),
            403: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="Signals scouts or the Run scout step are not enabled for this project, or the workflow lives in a child environment",
            ),
            404: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="No runnable scout of that name exists in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="A run for this scout is already in flight, or the scout is paused",
            ),
            422: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow no longer exists",
            ),
            429: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow cooldown, the daily run budget, the Signals credits quota, or the daily report limit binds",
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
        # One key per workflow step across the fetch retry chain, which re-sends the identical
        # request. Scoped under the verified team + workflow so a key is only ever replayed to the
        # caller that minted it.
        step_key = serializer.validated_data.get("idempotency_key")
        replay_key = f"workflow_scout_run:{team_id}:{hog_flow_id}:{step_key}" if step_key else None

        # A token outlives the workflow it was minted for (its TTL covers the whole fetch retry
        # chain), so a deleted workflow must not still be able to spend runs.
        if not HogFlow.objects.filter(team_id=team_id, id=hog_flow_id).exists():
            return _rejected("Workflow no longer exists.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        # The template's rollout flag gates the step at save time, but a lenient draft save skips
        # that and a draft test run executes the step for real, so the gate is re-checked here.
        if not _run_scout_enabled(team_id):
            return _rejected(
                "Running a scout from a workflow is not enabled for this project.", status.HTTP_403_FORBIDDEN
            )

        # Claim the key atomically before dispatching. A retry that arrives while the first
        # attempt is still dispatching (the client gave up on it, but Django is still in the
        # Temporal start) must not read an empty cache and race it.
        claimed = bool(replay_key) and cache.add(replay_key, _PENDING, timeout=_REPLAY_TTL_S)
        if replay_key and not claimed:
            # The original 202 was lost in transit but the run is already going; re-answer it
            # rather than let the retry collide with its own run (a 409 the step would record
            # as a skip). A still-pending sibling falls through: the in-flight collision below
            # is how it learns the outcome.
            replayed = _replay(cache.get(replay_key), skill_name)
            if replayed is not None:
                self._log_replay(team_id, hog_flow_id, skill_name, replayed, step_key)
                return _started(replayed.skill_name, replayed.workflow_id)

        try:
            started = start_workflow_scout_run(team_id=team_id, skill_name=skill_name)
        except WorkflowScoutRunRejected as error:
            if replay_key and claimed:
                # Nothing ran, so a later fire under the same key must be judged afresh.
                cache.delete(replay_key)
            elif replay_key and error.in_flight_workflow_id:
                # The run this collided with is the sibling's if the key is still held. It has
                # passed the same gates this request just did, so the only outcome that would
                # make the 202 wrong is a third run beating both, which the sibling's own
                # rejection (and its key release) would have shown here.
                marker = cache.get(replay_key)
                if marker is not None:
                    replayed = _replay(marker, skill_name) or WorkflowScoutRunStarted(
                        skill_name=skill_name, workflow_id=error.in_flight_workflow_id
                    )
                    self._log_replay(team_id, hog_flow_id, skill_name, replayed, step_key)
                    return _started(replayed.skill_name, replayed.workflow_id)
            rejection = error.rejection
            logger.info(
                "workflow_scout_run_rejected",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                skill_name=skill_name,
                reason=rejection.reason,
                step_key=step_key,
            )
            return _rejected(rejection.detail, _REJECTION_STATUS[rejection.kind])
        except BaseException:
            if replay_key and claimed:
                cache.delete(replay_key)
            raise

        if replay_key:
            cache.set(
                replay_key,
                {"skill_name": started.skill_name, "workflow_id": started.workflow_id},
                timeout=_REPLAY_TTL_S,
            )
        logger.info(
            "workflow_scout_run_started",
            team_id=team_id,
            hog_flow_id=str(hog_flow_id),
            skill_name=started.skill_name,
            workflow_id=started.workflow_id,
            step_key=step_key,
        )
        return _started(started.skill_name, started.workflow_id)

    @staticmethod
    def _log_replay(
        team_id: int, hog_flow_id: uuid.UUID, skill_name: str, replayed: WorkflowScoutRunStarted, step_key: str | None
    ) -> None:
        logger.info(
            "workflow_scout_run_replayed",
            team_id=team_id,
            hog_flow_id=str(hog_flow_id),
            skill_name=skill_name,
            workflow_id=replayed.workflow_id,
            step_key=step_key,
        )


def _run_scout_enabled(team_id: int) -> bool:
    flag_key = FLAG_GATED_TEMPLATE_IDS.get(RUN_SCOUT_TEMPLATE_ID)
    if flag_key is None:
        return True
    return gated_template_enabled(flag_key, Team.objects.get(pk=team_id))


def _replay(marker: Any, skill_name: str) -> WorkflowScoutRunStarted | None:
    """The dispatched run a cached marker records, or None while it is still the pending claim."""
    if not isinstance(marker, dict) or "workflow_id" not in marker:
        return None
    return WorkflowScoutRunStarted(skill_name=marker.get("skill_name") or skill_name, workflow_id=marker["workflow_id"])


def _started(skill_name: str, workflow_id: str) -> Response:
    return Response(
        WorkflowScoutRunResponseSerializer(
            {"skill_name": skill_name, "workflow_id": workflow_id, "started": True}
        ).data,
        status=status.HTTP_202_ACCEPTED,
    )


def _rejected(detail: str, http_status: int) -> Response:
    return Response(WorkflowScoutRunRejectedSerializer({"detail": detail}).data, status=http_status)
