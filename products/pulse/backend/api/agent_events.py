"""Internal callback for a pulse agent run's sandbox event stream.

Not a DRF viewset action — no team scoping. Auth is the per-run sandbox
event-ingest JWT (RS256; only the sandbox holds it). The sandbox agent-server
POSTs its event NDJSON here; on a turn-complete event we complete the async
Temporal activity that ``launch_agent_activity`` left pending, which lets the
workflow move on to read the report. Registered at:
``internal/pulse/runs/<run_id>/agent-events/``.
"""

import asyncio
import logging

from django.http import HttpRequest, JsonResponse

from jwt import PyJWTError

from products.pulse.backend.agent.async_completion import line_signals_turn_complete, pop_completion_context

logger = logging.getLogger(__name__)

# Mirrors the sibling task event-ingest cap (event_ingest.py): the body is untrusted agent output,
# so bound it before buffering into worker memory. Raw request.body is not covered by Django's
# DATA_UPLOAD_MAX_MEMORY_SIZE (that guards form parsing only).
MAX_REQUEST_BYTES = 5_000_000


def pulse_agent_events(request: HttpRequest, run_id: str) -> JsonResponse:
    # Inline to keep the sandbox/temporal deps off the URLconf import path (this module is
    # imported at startup when the routes are registered).
    from products.tasks.backend.facade.sandbox import (  # noqa: PLC0415 — keep sandbox deps off the import path
        validate_sandbox_event_ingest_token,
    )

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)
    token = authorization[len("Bearer ") :].strip()
    try:
        claims = validate_sandbox_event_ingest_token(token)
    except PyJWTError as exc:
        return JsonResponse({"error": "Invalid event ingest token", "code": exc.__class__.__name__}, status=401)
    # The JWT carries the run it was minted for; a mismatch means a token replayed across runs.
    if claims.run_id != run_id:
        return JsonResponse({"error": "Token does not match run"}, status=403)

    try:
        content_length = int(request.headers.get("Content-Length") or 0)
    except ValueError:
        content_length = 0
    if content_length > MAX_REQUEST_BYTES:
        return JsonResponse({"error": "Request body too large"}, status=413)

    body = request.body.decode("utf-8", errors="replace")
    if any(line_signals_turn_complete(line) for line in body.splitlines()):
        _complete_run(run_id)
    # Non-terminal events (progress chunks) need no action; always 200 so the agent-server keeps streaming.
    return JsonResponse({"status": "ok"})


def _complete_run(run_id: str) -> None:
    from posthog.temporal.common.client import (  # noqa: PLC0415 — keep temporalio off the URLconf import path
        sync_connect,
    )

    # First-wins: a duplicate turn-complete event finds no context and is a no-op, so the async
    # activity is completed at most once.
    context = pop_completion_context(run_id)
    if context is None:
        return
    try:
        client = sync_connect()
        handle = client.get_async_activity_handle(task_token=context.task_token)
        asyncio.run(handle.complete({"sandbox_id": context.sandbox_id}))
    except Exception:
        # The activity's schedule-to-close timeout is the backstop if completion can't be delivered.
        logger.exception("pulse_agent_events_complete_failed", extra={"run_id": run_id})
