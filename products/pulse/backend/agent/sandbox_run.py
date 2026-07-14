"""One mission = one sandbox lifetime, split across the async-completion seam.

Everything that leaves the sandbox is untrusted; this module only moves bytes.
Validation happens in trusted code on the other side of the activity edge. The
OAuth token is minted here (not in the mission bundle) so it never enters
Temporal payloads or persisted workflow history.

``launch_mission`` creates the sandbox, points its event stream at the pulse
callback, and delivers the mission — it does NOT wait for the turn or tear the
sandbox down, so the worker thread is freed via async activity completion. When
the callback reports the turn finished, ``finalize_mission`` reconnects to the
sandbox by id, reads the report, and tears it down.
"""

import json
import dataclasses
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

import structlog

from posthog.models.user import User
from posthog.storage import object_storage
from posthog.temporal.oauth import create_oauth_access_token_for_user

from products.pulse.backend.agent.mission import MissionBundle
from products.pulse.backend.agent.prompt import REPORT_PATH, render_mission_prompt
from products.tasks.backend.facade.sandbox import (
    McpServerConfig,
    SandboxConfig,
    SandboxNotFoundError,
    build_sandbox_environment_variables,
    create_sandbox_connection_token,
    create_sandbox_event_ingest_token,
    get_sandbox_class,
    send_agent_command,
)

logger = structlog.get_logger(__name__)

MAX_REPORT_BYTES = 512 * 1024  # stays far under Temporal's ~2 MiB payload cap
# The transcript is object-storage-bound (not a Temporal payload), so it can be looser than the
# report — but still capped at the source with `head -c` so a chatty agent can't spike worker memory.
MAX_TRANSCRIPT_BYTES = 1024 * 1024
# Delivery only has to hand off the mission, not wait for the turn: a read timeout comes back as
# turn_in_flight ("delivered, turn now running"), which is the expected outcome. Kept short so the
# activity can free its worker thread promptly and let the callback drive completion.
MISSION_DELIVERY_TIMEOUT_SECONDS = 60
# The agent-server streams its events here; the callback completes the async activity on turn end.
# Built off the sandbox's own POSTHOG_API_URL so it uses the same reachable Django base, and the
# sandbox command builder rewrites the host for container networking.
_AGENT_EVENTS_PATH = "internal/pulse/runs/{run_id}/agent-events/"


def _event_ingest_url(env: dict[str, str], run_id: str) -> str:
    base = (env.get("POSTHOG_API_URL") or settings.SITE_URL).rstrip("/")
    return f"{base}/{_AGENT_EVENTS_PATH.format(run_id=run_id)}"


class MissionRunError(Exception):
    pass


class ReportTooLargeError(MissionRunError):
    pass


@dataclasses.dataclass
class MissionRunResult:
    report: dict[str, Any]
    agent_session_ref: str
    transcript_key: str | None


@dataclasses.dataclass
class _SandboxRunRef:
    """Run-shaped object the sandbox command/token helpers duck-type against
    (see products.tasks.backend.facade.sandbox.SandboxRunRef) — no TaskRun row needed."""

    id: str
    task_id: str
    team_id: int
    mode: str
    state: dict[str, Any] | None


def _allowed_domains(bundle: MissionBundle) -> list[str]:
    hosts: dict[str, None] = {}
    for grant in bundle.tool_grants:
        host = urlparse(grant.url).hostname
        if host:
            hosts.setdefault(host, None)
    gateway = urlparse(settings.SANDBOX_LLM_GATEWAY_URL or "").hostname
    if gateway:
        hosts.setdefault(gateway, None)
    return list(hosts)


def _read_report(sandbox: Any) -> dict[str, Any]:
    # head -c bounds the read in the sandbox (one over the cap so an oversized report is still
    # detectable) rather than buffering an arbitrarily large file into worker memory first.
    out = sandbox.execute(f"head -c {MAX_REPORT_BYTES + 1} {REPORT_PATH} 2>/dev/null || true", timeout_seconds=30)
    raw = out.stdout.strip()
    if not raw:
        raise MissionRunError("Agent finished without writing a report")
    if len(raw.encode()) > MAX_REPORT_BYTES:
        raise ReportTooLargeError(f"Agent report exceeds {MAX_REPORT_BYTES} bytes")
    try:
        report = json.loads(raw)
    except ValueError as err:
        raise MissionRunError(f"Agent report is not valid JSON: {err}") from err
    if not isinstance(report, dict):
        raise MissionRunError("Agent report must be a JSON object")
    return report


def _persist_transcript(sandbox: Any, bundle: MissionBundle) -> str | None:
    # head -c caps the read in the sandbox so an oversized log never crosses into worker memory.
    log = sandbox.execute(
        f"head -c {MAX_TRANSCRIPT_BYTES} /tmp/agent-server.log 2>/dev/null || true", timeout_seconds=30
    ).stdout
    if not log:
        return None
    key = f"pulse/briefs/{bundle.team_id}/{bundle.brief_id}/agent-server.log"
    try:
        object_storage.write(key, log)
    except Exception as err:
        # Transcript loss degrades transparency, not correctness — never fail the run for it.
        logger.exception("pulse_transcript_upload_failed", brief_id=bundle.brief_id, error=str(err))
        return None
    return key


def _safe_destroy(sandbox: Any, *, brief_id: str, run_id: str) -> None:
    # A destroy failure must never mask the exception already propagating, and the sandbox
    # self-expires on its own TTL if this fails.
    try:
        sandbox.destroy()
    except Exception:
        logger.exception("pulse_sandbox_teardown_failed", brief_id=brief_id, run_id=run_id)


def launch_mission(
    bundle: MissionBundle,
    *,
    user: User,
    run_id: str,
    on_sandbox_created: Callable[[str], None],
) -> str:
    """Create the sandbox, start its agent-server streaming to the pulse callback, and deliver
    the mission. Returns the sandbox id; the sandbox is left running for the turn. Tears the
    sandbox down only if delivery fails (no finalize will run in that case)."""
    token = create_oauth_access_token_for_user(user, bundle.team_id, scopes=bundle.required_scopes)
    # Instances, not raw dicts: the sandbox implementations call .to_dict() on each entry.
    mcp_configs = [McpServerConfig(**grant.to_mcp_server_config(token=token)) for grant in bundle.tool_grants]
    allowed_domains = _allowed_domains(bundle)
    environment_variables = build_sandbox_environment_variables(None, token, bundle.team_id)
    event_ingest_url = _event_ingest_url(environment_variables, run_id)
    # Authenticates the agent-server's event-stream POSTs to the pulse callback; minted off a
    # run-shaped ref (no TaskRun row), signed with the primary key (empty state -> primary kid).
    ingest_ref = _SandboxRunRef(id=run_id, task_id=bundle.brief_id, team_id=bundle.team_id, mode="background", state={})
    event_ingest_token = create_sandbox_event_ingest_token(ingest_ref)

    sandbox_class = get_sandbox_class()
    sandbox = sandbox_class.create(
        SandboxConfig(
            name=f"pulse-{bundle.brief_id}",
            environment_variables=environment_variables,
            outbound_domain_allowlist=allowed_domains,
            metadata={"product": "pulse", "brief_id": bundle.brief_id, "team_id": str(bundle.team_id)},
        )
    )
    try:
        # Stash the completion context before the turn can start: delivery is what triggers the
        # turn, so the token is always resolvable before any turn-complete callback can arrive.
        on_sandbox_created(sandbox.id)
        credentials = sandbox.get_connect_credentials()
        sandbox.start_agent_server(
            repository=None,
            task_id=bundle.brief_id,
            run_id=run_id,
            mode="background",
            create_pr=False,
            mcp_configs=mcp_configs,
            allowed_domains=allowed_domains,
            event_ingest_url=event_ingest_url,
            event_ingest_token=event_ingest_token,
            wait_for_health=True,
        )
        run_ref = _SandboxRunRef(
            id=run_id,
            task_id=bundle.brief_id,
            team_id=bundle.team_id,
            mode="background",
            state={"sandbox_url": credentials.url, "sandbox_connect_token": credentials.token},
        )
        result = send_agent_command(
            run_ref,
            method="user_message",
            # messageId is the delivery idempotency key: a redelivered mission is ignored.
            params={"content": render_mission_prompt(bundle), "messageId": f"mission-{bundle.brief_id}"},
            timeout=MISSION_DELIVERY_TIMEOUT_SECONDS,
            auth_token=create_sandbox_connection_token(run_ref, user.id, user.distinct_id),
        )
        # turn_in_flight is the expected "delivered, turn now running"; success means a fast turn
        # already finished (its turn-complete event still drives the callback). Neither -> failure.
        if not result.success and not result.turn_in_flight:
            # One grep target for the failure: brief + run identify the sandbox in Temporal.
            logger.error(
                "pulse_mission_delivery_failed",
                brief_id=bundle.brief_id,
                run_id=run_id,
                status_code=result.status_code,
                error=result.error,
            )
            raise MissionRunError(f"Mission delivery failed: {result.error or result.status_code}")
        return sandbox.id
    except Exception:
        _safe_destroy(sandbox, brief_id=bundle.brief_id, run_id=run_id)
        raise


def finalize_mission(sandbox_id: str, bundle: MissionBundle, *, run_id: str) -> MissionRunResult:
    """Reconnect to the (turn-complete) sandbox, read its report and transcript, tear it down."""
    sandbox = get_sandbox_class().get_by_id(sandbox_id)
    try:
        report = _read_report(sandbox)
        transcript_key = _persist_transcript(sandbox, bundle)
        return MissionRunResult(report=report, agent_session_ref=sandbox_id, transcript_key=transcript_key)
    finally:
        _safe_destroy(sandbox, brief_id=bundle.brief_id, run_id=run_id)


def cleanup_sandbox(sandbox_id: str) -> None:
    """Best-effort teardown of an orphaned sandbox (callback never arrived). A sandbox that has
    already self-expired is not an error."""
    try:
        sandbox = get_sandbox_class().get_by_id(sandbox_id)
    except SandboxNotFoundError:
        return
    try:
        sandbox.destroy()
    except Exception:
        logger.exception("pulse_orphaned_sandbox_cleanup_failed", sandbox_id=sandbox_id)
