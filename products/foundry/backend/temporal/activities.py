"""Temporal activities for the foundry-run-bet workflow tree.

Two activities do all the work: ``run_node_activity`` provisions a sandbox (via the tasks
facade) and runs a node's command, and ``record_bet_event_activity`` writes a BetEvent
through the same facade external orchestrators POST through — so the managed and grey-box
paths produce an identical event log and BetNode tree (see ``logic/nodes.py``).
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.facade.sandbox import SandboxConfig, SandboxTemplate, get_sandbox_class_for_backend

from .constants import (
    FOUNDRY_EVENT_HELPER_PATH,
    FOUNDRY_EVENT_HELPER_SCRIPT,
    FOUNDRY_EVENT_PREFIX,
    FOUNDRY_MEMORY_MOUNT_PATH,
)


@dataclass
class RecordEventInput:
    bet_id: str
    team_id: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunNodeInput:
    node_id: str
    command: str
    env: dict[str, str] = field(default_factory=dict)
    memory_repo_url: str | None = None


@dataclass
class RunNodeOutput:
    exit_code: int
    spawn_requests: list[dict[str, Any]]
    knowledge_events: list[dict[str, Any]]
    notes: list[str]
    sandbox_external_id: str


def _resolve_sandbox_backend() -> str:
    """Map the shared ``SANDBOX_PROVIDER`` setting onto a get_sandbox_class_for_backend key."""
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    return provider if provider else "modal"


def _parse_foundry_events(stdout: str) -> list[dict[str, Any]]:
    """Pick ``##FOUNDRY_EVENT## {...}`` lines out of a node's raw stdout.

    Malformed lines (a JSON error, a non-object payload) are dropped rather than failing
    the whole node — a node's own command output is otherwise arbitrary and untrusted.
    """
    parsed: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.startswith(FOUNDRY_EVENT_PREFIX):
            continue
        try:
            event = json.loads(line[len(FOUNDRY_EVENT_PREFIX) :].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            parsed.append(event)
    return parsed


@activity.defn
@asyncify
def run_node_activity(input: RunNodeInput) -> RunNodeOutput:
    """Provision a sandbox, install the in-sandbox helper, run the node's command.

    The helper (``foundry-event``) lets the command declare structured events on its own
    stdout — spawning a child is the one kind the workflow itself must act on (only a
    workflow may start a child workflow); knowledge/note events are just recorded here.
    """
    sandbox_class = get_sandbox_class_for_backend(_resolve_sandbox_backend())
    config = SandboxConfig(
        name=f"foundry-node-{input.node_id}"[:63],
        template=SandboxTemplate.SLIM_BASE,
        environment_variables=input.env or None,
        metadata={"foundry_node_id": input.node_id},
    )
    sandbox = sandbox_class.create(config)
    notes: list[str] = []
    try:
        sandbox.write_file(FOUNDRY_EVENT_HELPER_PATH, FOUNDRY_EVENT_HELPER_SCRIPT.encode())
        sandbox.execute(f"chmod +x {shlex.quote(FOUNDRY_EVENT_HELPER_PATH)}")

        if input.memory_repo_url:
            clone = sandbox.execute(
                f"git clone --depth 1 {shlex.quote(input.memory_repo_url)} {shlex.quote(FOUNDRY_MEMORY_MOUNT_PATH)}",
                timeout_seconds=120,
            )
            if clone.exit_code != 0:
                notes.append(f"memory repo unreachable, continuing without it: {clone.stderr[:300]}")

        result = sandbox.execute(input.command, timeout_seconds=600)
    finally:
        try:
            sandbox.destroy()
        except Exception:
            activity.logger.exception(f"Failed to destroy sandbox for node {input.node_id}")

    events = _parse_foundry_events(result.stdout)
    spawn_requests = [e for e in events if e.get("type") == "spawn_child"]
    knowledge_events = [e for e in events if e.get("type") == "knowledge_published"]
    notes.extend(str(e.get("message", "")) for e in events if e.get("type") == "note")

    return RunNodeOutput(
        exit_code=result.exit_code,
        spawn_requests=spawn_requests,
        knowledge_events=knowledge_events,
        notes=notes,
        sandbox_external_id=sandbox.id,
    )


@activity.defn
@asyncify
def record_bet_event_activity(input: RecordEventInput) -> None:
    """Append a BetEvent through the foundry facade — the same path external POSTs use.

    A ``BetStateError`` (e.g. the bet was archived by a verdict while this run was still
    going) is logged and swallowed: these are the managed run's own bookkeeping events, and
    a state race on a side observation must not crash the whole node tree.
    """
    from products.foundry.backend.facade import api as foundry_api  # noqa: PLC0415
    from products.foundry.backend.facade.enums import BetEventKind  # noqa: PLC0415

    try:
        foundry_api.record_event(input.team_id, input.bet_id, BetEventKind(input.kind), input.payload)
    except foundry_api.BetStateError:
        activity.logger.warning(f"foundry: dropped {input.kind} event for bet {input.bet_id} (state race)")
