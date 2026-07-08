"""One mission = one sandbox lifetime.

Everything that leaves the sandbox is untrusted; this module only moves bytes.
Validation happens in trusted code on the other side of the activity edge. The
OAuth token is minted here (not in the mission bundle) so it never enters
Temporal payloads or persisted workflow history.
"""

import json
import time
import dataclasses
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
    build_sandbox_environment_variables,
    create_sandbox_connection_token,
    get_sandbox_class,
    send_agent_command,
)

logger = structlog.get_logger(__name__)

MAX_REPORT_BYTES = 512 * 1024  # stays far under Temporal's ~2 MiB payload cap
AGENT_TURN_TIMEOUT_SECONDS = 25 * 60  # inside the 30-min activity start_to_close
REPORT_POLL_INTERVAL_SECONDS = 10
REPORT_POLL_ATTEMPTS = 30  # only reached when the turn outlived the read timeout but may still be writing


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
    out = sandbox.execute(f"cat {REPORT_PATH} 2>/dev/null || true", timeout_seconds=30)
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
    log = sandbox.execute("cat /tmp/agent-server.log 2>/dev/null || true", timeout_seconds=30).stdout
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


def run_mission(bundle: MissionBundle, *, user: User, run_id: str) -> MissionRunResult:
    token = create_oauth_access_token_for_user(user, bundle.team_id, scopes=bundle.required_scopes)
    # Instances, not raw dicts: the sandbox implementations call .to_dict() on each entry.
    mcp_configs = [McpServerConfig(**grant.to_mcp_server_config(token=token)) for grant in bundle.tool_grants]
    allowed_domains = _allowed_domains(bundle)

    sandbox_class = get_sandbox_class()
    sandbox = sandbox_class.create(
        SandboxConfig(
            name=f"pulse-{bundle.brief_id}",
            environment_variables=build_sandbox_environment_variables(None, token, bundle.team_id),
            outbound_domain_allowlist=allowed_domains,
            metadata={"product": "pulse", "brief_id": bundle.brief_id, "team_id": str(bundle.team_id)},
        )
    )
    try:
        credentials = sandbox.get_connect_credentials()
        sandbox.start_agent_server(
            repository=None,
            task_id=bundle.brief_id,
            run_id=run_id,
            mode="background",
            create_pr=False,
            mcp_configs=mcp_configs,
            allowed_domains=allowed_domains,
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
            timeout=AGENT_TURN_TIMEOUT_SECONDS,
            auth_token=create_sandbox_connection_token(run_ref, user.id, user.distinct_id),
        )
        if not result.success and not result.turn_in_flight:
            raise MissionRunError(f"Mission delivery failed: {result.error or result.status_code}")
        if result.turn_in_flight:
            # Delivery succeeded but the turn outlived our read timeout: poll for the report.
            for _ in range(REPORT_POLL_ATTEMPTS):
                probe = sandbox.execute(f"test -s {REPORT_PATH} && echo done || true", timeout_seconds=10)
                if probe.stdout.strip() == "done":
                    break
                time.sleep(REPORT_POLL_INTERVAL_SECONDS)
        report = _read_report(sandbox)
        transcript_key = _persist_transcript(sandbox, bundle)
        return MissionRunResult(report=report, agent_session_ref=sandbox.id, transcript_key=transcript_key)
    finally:
        # Teardown ends the credential's usefulness alongside the sandbox; the OAuth
        # token itself auto-expires (see posthog/temporal/oauth.py).
        sandbox.destroy()
