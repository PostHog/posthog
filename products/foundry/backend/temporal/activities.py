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

from products.tasks.backend.facade.sandbox import (
    ExecutionResult,
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class_for_backend,
)

from ..logic.redaction import redact_secret_values, secret_values_from_env
from .constants import (
    FOUNDRY_AGENT_USER,
    FOUNDRY_CLAUDE_CLI_PACKAGE,
    FOUNDRY_EVENT_HELPER_PATH,
    FOUNDRY_EVENT_HELPER_SCRIPT,
    FOUNDRY_EVENT_LOG_PATH,
    FOUNDRY_EVENT_PREFIX,
    FOUNDRY_MEMORY_MOUNT_PATH,
    FOUNDRY_TARGET_REPO_PATH,
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
    # Build-loop nodes only (see build_workflow.py): a target_repo to check out before
    # `command` runs. Unlike memory_repo_url this is fatal on failure — it's the artifact
    # source, not a nice-to-have.
    target_repo_url: str | None = None
    target_repo_ref: str | None = None
    # Installs the Claude Code CLI at sandbox-startup time rather than baking a dedicated
    # image layer — see build_workflow.py's module docstring for the tradeoff.
    install_claude_cli: bool = False
    # A real coding-agent run takes much longer than a scripted demo command; build-loop
    # callers raise this well past the 600s default (and must raise their activity's own
    # start_to_close_timeout to match — this is just the sandbox-level exec timeout).
    command_timeout_seconds: int = 600


@dataclass
class _SyntheticExecResult:
    """Stands in for a real ``ExecutionResult`` when a pre-command setup step (target repo
    checkout, claude CLI install) fails and ``input.command`` never runs at all."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class RunNodeOutput:
    exit_code: int
    spawn_requests: list[dict[str, Any]]
    knowledge_events: list[dict[str, Any]]
    notes: list[str]
    sandbox_external_id: str
    # Defaults to [] so old recorded activity results (from before this field existed) decode
    # cleanly on replay — see the workflow-versioning rule: a new workflow command gated on a
    # new defaulted output field never fires while replaying an old history.
    artifact_ready_events: list[dict[str, Any]] = field(default_factory=list)


def _resolve_sandbox_backend() -> str:
    """Map the shared ``SANDBOX_PROVIDER`` setting onto a get_sandbox_class_for_backend key."""
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    return provider if provider else "modal"


FOUNDRY_AGENT_SCRIPT_PATH = "/tmp/foundry-agent-command.sh"


def _run_as_agent_user(sandbox: Any, command: str, env: dict[str, str]) -> str:
    """Wrap ``command`` to run as the unprivileged ``FOUNDRY_AGENT_USER`` instead of the
    sandbox's default root — required for ``claude --dangerously-skip-permissions``, which
    refuses to run as root regardless of sandboxing (see constants.py).

    ``command`` is an arbitrary, unquoted multi-line agent prompt (a real one is full of
    apostrophes and its own nested quoting, e.g. a heredoc) — passing it through
    ``shlex.quote()`` as an argument to ``su -c`` breaks exactly like it broke here: quoting
    escapes every literal apostrophe in the prose indiscriminately, since a generic quoting
    function can't tell a "structural" quote from a content one, corrupting the heredoc and
    splitting the prompt into dozens of stray argv words. Writing it to a script file (the
    same mechanism the foundry-event helper already uses) sidesteps quoting entirely — the
    file's bytes are never re-parsed as shell syntax, they're just what ``sh`` reads.
    """
    sandbox.execute(
        f"id -u {shlex.quote(FOUNDRY_AGENT_USER)} >/dev/null 2>&1 || useradd -m -s /bin/sh {shlex.quote(FOUNDRY_AGENT_USER)}"
    )
    sandbox.execute(
        f"chown -R {shlex.quote(FOUNDRY_AGENT_USER)}:{shlex.quote(FOUNDRY_AGENT_USER)} {shlex.quote(FOUNDRY_TARGET_REPO_PATH)}"
    )
    # su drops the calling environment, so every env var is re-exported explicitly — each is
    # its own `export NAME=value` line, safely shlex-quoted on its own (not nested inside a
    # larger quoted string), so this is fine even though `command` below isn't quoted at all.
    env_prefix = "".join(f"export {name}={shlex.quote(value)}\n" for name, value in env.items())
    # A fresh user has no git identity; every build-loop node commits, so configure one
    # rather than making every reference prompt tell the agent to do it itself.
    git_identity = (
        "git config --global user.email foundry-agent@posthog.com\ngit config --global user.name 'Foundry builder'\n"
    )
    script = f"#!/bin/sh\n{env_prefix}{git_identity}{command}\n"
    sandbox.write_file(FOUNDRY_AGENT_SCRIPT_PATH, script.encode())
    return f"su {shlex.quote(FOUNDRY_AGENT_USER)} -s /bin/sh {shlex.quote(FOUNDRY_AGENT_SCRIPT_PATH)}"


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
    result: ExecutionResult | _SyntheticExecResult | None = None
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

        # Unlike the memory repo above, a build-loop node's target_repo IS the artifact
        # source — a failure here is fatal to the node, not a degrade-and-continue case.
        if input.target_repo_url:
            clone = sandbox.execute(
                f"git clone {shlex.quote(input.target_repo_url)} {shlex.quote(FOUNDRY_TARGET_REPO_PATH)}",
                timeout_seconds=120,
            )
            if clone.exit_code != 0:
                notes.append(f"target repo clone failed: {clone.stderr[:300]}")
                result = _SyntheticExecResult(exit_code=clone.exit_code)
            elif input.target_repo_ref:
                checkout = sandbox.execute(
                    f"cd {shlex.quote(FOUNDRY_TARGET_REPO_PATH)} && git checkout {shlex.quote(input.target_repo_ref)}",
                    timeout_seconds=60,
                )
                if checkout.exit_code != 0:
                    notes.append(f"target repo checkout of '{input.target_repo_ref}' failed: {checkout.stderr[:300]}")
                    result = _SyntheticExecResult(exit_code=checkout.exit_code)

        if result is None and input.install_claude_cli:
            install = sandbox.execute(f"npm install -g {shlex.quote(FOUNDRY_CLAUDE_CLI_PACKAGE)}", timeout_seconds=180)
            if install.exit_code != 0:
                notes.append(f"claude CLI install failed: {install.stderr[:300]}")
                result = _SyntheticExecResult(exit_code=install.exit_code)

        if result is None:
            command = input.command
            if input.target_repo_url:
                command = f"cd {shlex.quote(FOUNDRY_TARGET_REPO_PATH)} && {command}"
            if input.install_claude_cli:
                command = _run_as_agent_user(sandbox, command, input.env)
            result = sandbox.execute(command, timeout_seconds=input.command_timeout_seconds)
            # A build-loop node's command is a real agent run, not a scripted demo — capture
            # why it failed rather than leaving only a bare exit code to debug from.
            if input.install_claude_cli and result.exit_code != 0:
                tail = "\n".join((result.stdout + result.stderr).splitlines()[-20:])
                notes.append(f"node command failed (exit {result.exit_code}): {tail[:500]}")
        event_log_text = ""
        if input.install_claude_cli:
            try:
                event_log = sandbox.execute(f"cat {shlex.quote(FOUNDRY_EVENT_LOG_PATH)} 2>/dev/null || true")
                event_log_text = event_log.stdout
            except Exception:
                activity.logger.exception(f"Failed to read foundry-event log for node {input.node_id}")
    finally:
        try:
            sandbox.destroy()
        except Exception:
            activity.logger.exception(f"Failed to destroy sandbox for node {input.node_id}")

    assert result is not None  # the final unconditional branch above always assigns it

    secrets = secret_values_from_env(input.env)
    # A real coding agent's own stdout is its paraphrased final response, not a raw passthrough
    # of what its tool calls wrote — a scripted demo's sentinel line lands in result.stdout
    # directly, but a real agent's foundry-event call doesn't reliably show up there, only in
    # the log file the helper also appends to. Only fall back to the file when stdout parsing
    # found nothing, so every existing scripted-demo test (whose fake sandbox never simulates
    # the file) keeps working unchanged.
    parsed_events = _parse_foundry_events(result.stdout)
    if not parsed_events and event_log_text:
        parsed_events = _parse_foundry_events(event_log_text)
    events = [redact_secret_values(e, secrets) for e in parsed_events]
    spawn_requests = [e for e in events if e.get("type") == "spawn_child"]
    knowledge_events = [e for e in events if e.get("type") == "knowledge_published"]
    artifact_ready_events = [e for e in events if e.get("type") == "artifact_ready"]
    notes.extend(str(e.get("message", "")) for e in events if e.get("type") == "note")
    notes = [redact_secret_values(n, secrets) for n in notes]

    return RunNodeOutput(
        exit_code=result.exit_code,
        spawn_requests=spawn_requests,
        knowledge_events=knowledge_events,
        notes=notes,
        sandbox_external_id=sandbox.id,
        artifact_ready_events=artifact_ready_events,
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
