import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse

from drf_spectacular.utils import OpenApiResponse, extend_schema
from jwt import PyJWTError

from products.tasks.backend.models import TaskRun
from products.tasks.backend.presentation.serializers import (
    AgentProxyCallbackRequestSerializer,
    AgentProxyCallbackResponseSerializer,
    TaskRunErrorResponseSerializer,
)
from products.tasks.backend.push_dispatcher import notify_task_run_awaiting_input

logger = logging.getLogger(__name__)


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
    },
    summary="Agent-proxy side-effect callback",
    description=(
        "Internal endpoint called by the standalone Node agent-proxy after accepting an ingest event "
        "that requires a Django-side side effect. Dispatches a Temporal heartbeat signal or an "
        "awaiting-input mobile push notification depending on `kind`. "
        "Authenticated with the forwarded sandbox event ingest JWT plus the X-Agent-Proxy-Secret "
        "shared secret (required outside local dev/test) — no session or API key involved. "
        "Best-effort: always returns 200 when auth passes; side-effect failures are logged, not surfaced."
    ),
)
def agent_proxy_callback(request, run_id: str) -> JsonResponse:
    """Handle side-effect callbacks from the Node agent-proxy service.

    Auth: sandbox event ingest JWT forwarded from the Node service as a Bearer token.
    The JWT already carries run_id, task_id, team_id — body fields are validated
    against the JWT claims to prevent cross-run confusion.
    """
    from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the import path
        validate_sandbox_event_ingest_token,
    )

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Extract and validate the Bearer token
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)
    token = authorization[len("Bearer ") :].strip()
    if not token:
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)

    try:
        claims = validate_sandbox_event_ingest_token(token)
    except PyJWTError as exc:
        return JsonResponse({"error": "Invalid event ingest token", "code": exc.__class__.__name__}, status=401)

    # JWT run_id must match URL parameter
    if claims.run_id != run_id:
        return JsonResponse({"error": "Token does not match task run"}, status=403)

    # Service-to-service guard: the event-ingest JWT is also held by the sandbox, so the JWT alone
    # does not prove the caller is the agent-proxy. Require the shared secret so a sandbox cannot
    # drive this callback directly (bypassing the proxy's Redis sequencing/throttle). An unset
    # secret fails closed — the endpoint stays dead until the secret is provisioned — except in
    # local dev/test where no proxy deployment exists to share a secret with.
    expected_secret = settings.AGENT_PROXY_CALLBACK_SECRET
    if expected_secret:
        provided_secret = request.headers.get("X-Agent-Proxy-Secret", "")
        if not hmac.compare_digest(provided_secret, expected_secret):
            return JsonResponse({"error": "Invalid agent-proxy callback secret"}, status=403)
    elif not (settings.DEBUG or settings.TEST):
        return JsonResponse({"error": "Agent-proxy callback secret is not configured"}, status=403)

    # Validate and parse the request body
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    serializer = AgentProxyCallbackRequestSerializer(data=body)
    if not serializer.is_valid():
        return JsonResponse({"error": "Invalid request body", "detail": serializer.errors}, status=400)

    data = serializer.validated_data
    kind: str = data["kind"]
    task_id: str = data["task_id"]
    team_id: int = data["team_id"]
    agent_active: bool = data["agent_active"]

    # Body claims must match JWT claims to prevent cross-run confusion
    if task_id != claims.task_id or team_id != claims.team_id:
        return JsonResponse({"error": "Token claims do not match request body"}, status=403)

    dispatched = False

    if kind == "heartbeat" and agent_active:
        try:
            task_run = TaskRun.objects.get(id=run_id, task_id=task_id, team_id=team_id)
            task_run.heartbeat_workflow(agent_active=True)
            dispatched = True
        except TaskRun.DoesNotExist:
            logger.warning("agent_proxy_callback.run_not_found", extra={"run_id": run_id})
        except Exception:
            logger.exception("agent_proxy_callback.heartbeat_failed", extra={"run_id": run_id})

    elif kind == "awaiting_input":
        try:
            # The push dispatcher reads task.created_by; prefetch it so the dispatch stays one query.
            task_run = TaskRun.objects.select_related("task__created_by").get(
                id=run_id, task_id=task_id, team_id=team_id
            )
            if task_run.mode == "interactive":
                notify_task_run_awaiting_input(task_run)
                dispatched = True
        except TaskRun.DoesNotExist:
            logger.warning("agent_proxy_callback.run_not_found", extra={"run_id": run_id})
        except Exception:
            logger.exception("agent_proxy_callback.awaiting_input_failed", extra={"run_id": run_id})

    return JsonResponse(AgentProxyCallbackResponseSerializer({"dispatched": dispatched}).data)
