import hmac
import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from django.conf import settings
from django.http import HttpRequest, JsonResponse

from drf_spectacular.utils import OpenApiResponse, extend_schema
from jwt import PyJWTError

from posthog.dataclasses import frozen

from products.tasks.backend.facade.api import signal_workflow_completion
from products.tasks.backend.logic.services.process_killed import (
    PROCESS_KILLED_EVENT,
    ProcessKilledNotice,
    process_killed_event_uuid,
)
from products.tasks.backend.logic.stream.budget_steer import BudgetSteerCapture
from products.tasks.backend.logic.stream.event_ingest import _parse_budget_steer_properties
from products.tasks.backend.metrics import observe_sandbox_process_killed
from products.tasks.backend.models import TaskRun
from products.tasks.backend.presentation.serializers import (
    AgentProxyCallbackRequestSerializer,
    AgentProxyCallbackResponseSerializer,
    TaskRunErrorResponseSerializer,
)
from products.tasks.backend.turn_completed import dispatch_turn_completed

from ee.hogai.sandbox import PI_RUNTIME_ERROR_MESSAGE

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.connection_token import SandboxEventIngestTokenPayload

logger = logging.getLogger(__name__)

AgentBootMilestone = Literal["agent_command_dispatched", "agent_activity_observed"]

RETRYABLE_KINDS = frozenset({"budget_steer", "process_killed"})


class CallbackRejected(Exception):
    def __init__(self, status: int, error: str, **extra: Any) -> None:
        super().__init__(error)
        self.status = status
        self.payload: dict[str, Any] = {"error": error, **extra}

    def response(self) -> JsonResponse:
        return JsonResponse(self.payload, status=self.status)


@frozen
class CallbackOutcome:
    dispatched: bool = False
    status: int = 200
    error: str | None = None

    def response(self) -> JsonResponse:
        if self.error is not None:
            return JsonResponse({"error": self.error}, status=self.status)
        payload = AgentProxyCallbackResponseSerializer({"dispatched": self.dispatched}).data
        return JsonResponse(payload, status=self.status)


@frozen
class CallbackRequest:
    run_id: str
    claims: "SandboxEventIngestTokenPayload"
    body: dict[str, Any]
    data: dict[str, Any]

    @classmethod
    def from_request(cls, request: HttpRequest, run_id: str) -> "CallbackRequest":
        if request.method != "POST":
            raise CallbackRejected(405, "Method not allowed")
        claims = cls._authenticate(request, run_id)
        cls._check_proxy_secret(request)
        body = cls._parse_json(request)
        data = cls._validate(body)
        if data["task_id"] != claims.task_id or data["team_id"] != claims.team_id:
            raise CallbackRejected(403, "Token claims do not match request body")
        return cls(run_id=run_id, claims=claims, body=body, data=data)

    @staticmethod
    def _authenticate(request: HttpRequest, run_id: str) -> "SandboxEventIngestTokenPayload":
        from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the import path
            validate_sandbox_event_ingest_token,
        )

        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise CallbackRejected(401, "Missing authorization bearer token")
        token = authorization[len("Bearer ") :].strip()
        if not token:
            raise CallbackRejected(401, "Missing authorization bearer token")
        try:
            claims = validate_sandbox_event_ingest_token(token)
        except PyJWTError as exc:
            raise CallbackRejected(401, "Invalid event ingest token", code=exc.__class__.__name__) from exc
        if claims.run_id != run_id:
            raise CallbackRejected(403, "Token does not match task run")
        return claims

    @staticmethod
    def _check_proxy_secret(request: HttpRequest) -> None:
        # The event-ingest JWT is also held by the sandbox, so the JWT alone does not prove the caller
        # is the agent-proxy. Require the shared secret so a sandbox cannot drive this callback directly
        # (bypassing the proxy's Redis sequencing/throttle). An unset secret fails closed except in
        # local dev/test, where no proxy deployment exists to share a secret with.
        expected_secret = settings.AGENT_PROXY_CALLBACK_SECRET
        if expected_secret:
            provided_secret = request.headers.get("X-Agent-Proxy-Secret", "")
            if not hmac.compare_digest(provided_secret, expected_secret):
                raise CallbackRejected(403, "Invalid agent-proxy callback secret")
        elif not (settings.DEBUG or settings.TEST):
            raise CallbackRejected(403, "Agent-proxy callback secret is not configured")

    @staticmethod
    def _parse_json(request: HttpRequest) -> dict[str, Any]:
        try:
            return json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            raise CallbackRejected(400, "Invalid JSON body") from None

    @staticmethod
    def _validate(body: dict[str, Any]) -> dict[str, Any]:
        serializer = AgentProxyCallbackRequestSerializer(data=body)
        if not serializer.is_valid():
            raise CallbackRejected(400, "Invalid request body", detail=serializer.errors)
        return serializer.validated_data


class AgentProxyCallbackDispatcher:
    def __init__(self, callback: CallbackRequest) -> None:
        self.callback = callback
        self.run_id = callback.run_id
        self.task_id: str = callback.data["task_id"]
        self.team_id: int = callback.data["team_id"]
        self.kind: str = callback.data["kind"]

    def dispatch(self) -> CallbackOutcome:
        try:
            return self._dispatch_kind()
        except Exception:
            logger.exception(
                f"agent_proxy_callback.{self.kind}_failed", extra={"run_id": self.run_id, "kind": self.kind}
            )
            return CallbackOutcome(status=503) if self.kind in RETRYABLE_KINDS else CallbackOutcome()

    def _dispatch_kind(self) -> CallbackOutcome:
        match self.kind:
            case "heartbeat":
                return self._heartbeat()
            case "command_dispatched":
                return self._boot_milestone("agent_command_dispatched")
            case "agent_activity":
                return self._boot_milestone("agent_activity_observed")
            case "awaiting_input":
                return self._awaiting_input()
            case "turn_failed":
                return self._turn_failed()
            case "budget_steer":
                return self._budget_steer()
            case "process_killed":
                return self._process_killed()
        return CallbackOutcome()

    def _load_run(self, *related: str) -> TaskRun | None:
        queryset = TaskRun.objects.select_related(*related) if related else TaskRun.objects.all()
        try:
            return queryset.get(id=self.run_id, task_id=self.task_id, team_id=self.team_id)
        except TaskRun.DoesNotExist:
            logger.warning("agent_proxy_callback.run_not_found", extra={"run_id": self.run_id})
            return None

    def _heartbeat(self) -> CallbackOutcome:
        if not self.callback.data["agent_active"]:
            return CallbackOutcome()
        task_run = self._load_run()
        if task_run is None:
            return CallbackOutcome()
        task_run.heartbeat_workflow(agent_active=True, force=self.callback.data["activity_started"])
        return CallbackOutcome(dispatched=True)

    def _boot_milestone(self, milestone: AgentBootMilestone) -> CallbackOutcome:
        task_run = self._load_run()
        if task_run is None:
            return CallbackOutcome()
        return CallbackOutcome(dispatched=task_run.signal_agent_boot_milestone(milestone))

    def _awaiting_input(self) -> CallbackOutcome:
        # The push dispatcher reads task.created_by; prefetch it so the dispatch stays one query.
        task_run = self._load_run("task__created_by")
        if task_run is None:
            return CallbackOutcome()
        task_run.signal_agent_turn_completed(succeeded=self.callback.data["turn_succeeded"])
        dispatched = dispatch_turn_completed(task_run, turn_completed=self.callback.data["turn_completed"])
        return CallbackOutcome(dispatched=dispatched)

    def _turn_failed(self) -> CallbackOutcome:
        if self._load_run() is None:
            return CallbackOutcome()
        signal_workflow_completion(self.run_id, "failed", PI_RUNTIME_ERROR_MESSAGE)
        return CallbackOutcome(dispatched=True)

    def _budget_steer(self) -> CallbackOutcome:
        properties = _parse_budget_steer_properties(
            self.callback.claims, {"notification": {"method": "_posthog/budget_steer", "params": self.callback.body}}
        )
        sequence = self.callback.data.get("sequence")
        if sequence is None or properties is None:
            return CallbackOutcome(status=400, error="Invalid budget steer")
        BudgetSteerCapture.enqueue(self.team_id, self.run_id, sequence, properties, self.callback.body.get("timestamp"))
        return CallbackOutcome(dispatched=True)

    def _process_killed(self) -> CallbackOutcome:
        sequence = self.callback.data.get("sequence")
        killed = self.callback.data.get("process_killed")
        if sequence is None or killed is None:
            return CallbackOutcome(status=400, error="Invalid process kill")
        task_run = self._load_run("task__created_by", "team")
        if task_run is None:
            return CallbackOutcome()
        notice = ProcessKilledNotice(**killed)
        captured = task_run.capture_event(
            PROCESS_KILLED_EVENT,
            notice.analytics_properties(),
            event_uuid=process_killed_event_uuid(self.run_id, sequence),
        )
        if not captured:
            return CallbackOutcome(status=503)
        observe_sandbox_process_killed()
        return CallbackOutcome(dispatched=True)


# ---------------------------------------------------------------------------
# Internal agent-proxy callback (not a DRF viewset action — no team scoping,
# auth is the sandbox event ingest JWT forwarded by the Node service).
# Registered at: internal/tasks/runs/<run_id>/agent-proxy-callback/
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["task-runs"],
    request=AgentProxyCallbackRequestSerializer,
    responses={
        200: OpenApiResponse(
            response=AgentProxyCallbackResponseSerializer,
            description="Side effect dispatched or skipped",
        ),
        400: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Invalid request body"),
        401: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="Missing or invalid JWT"),
        403: OpenApiResponse(response=TaskRunErrorResponseSerializer, description="JWT claims do not match URL"),
        503: OpenApiResponse(response=AgentProxyCallbackResponseSerializer, description="Budget steer dispatch failed"),
    },
    summary="Agent-proxy side-effect callback",
    description=(
        "Internal endpoint called by the standalone Node agent-proxy after accepting an ingest event "
        "that requires a Django-side side effect. Dispatches a Temporal heartbeat, a boot milestone, "
        "an awaiting-input mobile push notification, a failed-run completion, budget-steer analytics, "
        "or a sandbox memory watchdog kill "
        "depending on `kind`. "
        "Authenticated with the forwarded sandbox event ingest JWT plus the X-Agent-Proxy-Secret "
        "shared secret (required outside local dev/test) — no session or API key involved. "
        "Budget steers are queued for capture, with 503 on dispatch failure so the proxy can retry."
    ),
)
def agent_proxy_callback(request, run_id: str) -> JsonResponse:
    try:
        callback = CallbackRequest.from_request(request, run_id)
    except CallbackRejected as rejection:
        return rejection.response()
    return AgentProxyCallbackDispatcher(callback).dispatch().response()
