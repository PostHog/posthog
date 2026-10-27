"""PostHog-specific telemetry property hooks.

Registers a hook that enriches every ``command_started`` / ``command_completed``
event with PostHog-developer context (process manager, devenv state, org
membership, etc.). Imports here are stdlib only — keep it light, this loads at
boot.
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import fcntl
import socket
import hashlib
import secrets
import functools
import contextlib
import subprocess
import configparser
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hogli.hooks import register_telemetry_properties
from hogli.manifest import REPO_ROOT
from hogli.telemetry import _load_config, _save_config, is_ci

from hogli_commands.test_runner import runs_on_playwright

_POSTHOG_DEV_CACHE_TTL_SECONDS = 30 * 86400  # 30 days


# Created by hogland's guest overlay (hog-env-materialise) on every hogbox
# boot; the guest exposes no ambient env var, so this path is the marker.
# Prefer baking HOGLI_ENVIRONMENT=hogland into the guest image -- this is the
# fallback until that ships.
_HOGLAND_MARKER = Path("/var/lib/hog")

# Coder sets these inside every workspace, which is what our devboxes run on.
_DEVBOX_ENV_MARKERS = ("CODER", "CODER_WORKSPACE_NAME")

# Ambient markers set by agent harnesses in the shells they spawn. Ordered
# most-specific first: posthog-code drives claude/codex under the hood, so its
# marker must win over theirs. Harnesses without an ambient marker can
# self-declare via HOGLI_AGENT instead.
_AGENT_ENV_MARKERS = (
    ("POSTHOG_CODE_VERSION", "posthog-code"),
    ("CLAUDECODE", "claude-code"),
    ("CODEX_SANDBOX", "codex"),
    ("CODEX_THREAD_ID", "codex"),
    ("CODEX_CI", "codex"),
    ("CURSOR_AGENT", "cursor"),
    ("GEMINI_CLI", "gemini-cli"),
    ("OPENCODE", "opencode"),
)

# Cross-tool convention for a harness to name itself, see https://huggingface.co/api/agent-harnesses
_STANDARD_AGENT_ENV_VARS = ("AI_AGENT", "AGENT")

_ACTOR_ENV_VAR = "HOGLI_ACTOR"

# Ordered like _AGENT_ENV_MARKERS: posthog-code runs claude or codex inside its task run,
# so the task run id must win over the session id of the inner harness.
_AGENT_SESSION_ENV_VARS = (
    "HOGLI_SESSION_ID",
    "POSTHOG_TASK_RUN_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_ID",
)

_PR_NUMBER_ENV_VARS = ("HOGLI_PR_NUMBER", "GITHUB_PR_NUMBER", "BUILDKITE_PULL_REQUEST")
_GITHUB_PULL_REF = re.compile(r"^refs/pull/(\d+)/")

_TELEMETRY_STATE_PATH = Path.home() / ".hogli" / "telemetry_state.json"
_STATE_LOCK_ATTEMPTS = 5
_STATE_LOCK_RETRY_SECONDS = 0.002
_RERUN_WINDOW_SECONDS = 30 * 60
_MAX_RECORDED_RUNS = 200
# The terminal session cache is keyed by the session leader pid. After this idle age the
# pid can belong to a new terminal, so the id is derived again from the leader start time.
_TERMINAL_SESSION_TTL_SECONDS = 12 * 3600
_MAX_CACHED_TERMINAL_SESSIONS = 50

CommandKind = Literal[
    "verify-lint",
    "verify-typecheck",
    "verify-test",
    "verify-preflight",
    "verify-e2e",
    "build",
    "run-stack",
    "devbox",
    "other",
]

_RUN_STACK_COMMANDS = frozenset(
    {"start", "up", "wait", "stop", "down", "dev:up", "services:ready", "db:migrate", "migrations:run"}
)
_LINT_COMMANDS = frozenset({"tool:ruff", "migrations:check"})
_NOT_TESTS = frozenset({"test:quarantine"})


def _declared(var: str) -> str:
    """Self-declared label from *var*, normalized so a sloppy export ('Sandbox ')
    can't fragment the telemetry dimension."""
    return os.environ.get(var, "").strip().lower()[:64]


def _detect_environment() -> str:
    """Classify where hogli is running: ci, devbox, hogland, local, or a self-declared value.

    Environments without an ambient marker (e.g. agent sandboxes) should export
    ``HOGLI_ENVIRONMENT`` in their bootstrap to self-declare.
    """
    declared = _declared("HOGLI_ENVIRONMENT")
    if declared:
        return declared
    # Unreachable while the CI gate disables telemetry entirely; kept so the
    # label can never diverge from the gate (same rationale as the is_ci prop).
    if is_ci():
        return "ci"
    # Checked before the hogland marker so Coder-on-hogland reads as a devbox.
    if any(os.environ.get(var) for var in _DEVBOX_ENV_MARKERS):
        return "devbox"
    if _HOGLAND_MARKER.exists():
        return "hogland"
    return "local"


def _detect_agent() -> str | None:
    """Name of the agent harness driving this invocation, or None when no harness declares itself."""
    declared = _declared("HOGLI_AGENT")
    if declared:
        return declared
    for var, agent in _AGENT_ENV_MARKERS:
        if os.environ.get(var):
            return agent
    for var in _STANDARD_AGENT_ENV_VARS:
        declared = _declared(var)
        if declared:
            # A version suffix (`name@1.2`, `name_1-2_agent`) would give each release its own value.
            name = re.split(r"[@_]\d", declared, maxsplit=1)[0]
            # `AGENT=1` is a bare flag, not a name.
            return "unknown" if name in {"", "1", "true"} else name
    return None


def _detect_actor(agent: str | None) -> Literal["agent", "human", "unknown"]:
    """Who drives this invocation. Human needs a terminal, so no agent and no terminal is unknown."""
    if agent is not None:
        return "agent"
    # A nested hogli command has captured streams, so it inherits the outermost verdict.
    if _declared(_ACTOR_ENV_VAR) == "human":
        return "human"
    # git pipes the pushed refs into a pre-push hook's stdin, so stdin alone misses a person's push.
    if any(os.isatty(fd) for fd in (0, 1, 2)):
        return "human"
    return "unknown"


@functools.cache
def _repo_commit() -> tuple[str, str] | None:
    """Short SHA and committer date of HEAD, identifying the checkout's vintage.

    --no-show-signature keeps gpg verification lines (log.showSignature=true)
    out of stdout, which would otherwise corrupt the parse.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", "-1", "--no-show-signature", "--format=%h %cI"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        sha, _, commit_date = result.stdout.strip().partition(" ")
        if not sha or not commit_date:
            return None
        return sha, commit_date
    except Exception:
        return None


def _repo_commit_properties() -> dict[str, str]:
    commit = _repo_commit()
    if commit is None:
        return {}
    return {"repo_sha": commit[0], "repo_commit_date": commit[1]}


@functools.cache
def _git_branch() -> str | None:
    """Current branch name — the join key from a hogli run back to its PR.

    "HEAD" (detached) and failures collapse to None so they don't pollute the
    dimension. Cached per process: hogli commands are short-lived, so the branch
    can't change mid-run.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch and branch != "HEAD" else None


def _infer_process_manager(command: str | None) -> str | None:
    pm = os.environ.get("HOGLI_PROCESS_MANAGER")
    if pm:
        return os.path.basename(pm)
    if command == "start":
        return "mprocs" if "--mprocs" in sys.argv[2:] else "phrocs"
    return None


def _check_email_domain() -> bool:
    """Fallback signal: git ``user.email`` ends with ``@posthog.com``."""
    parser = configparser.RawConfigParser()
    try:
        parser.read([Path.home() / ".gitconfig", REPO_ROOT / ".git" / "config"])
        email = parser.get("user", "email", fallback="")
        return email.endswith("@posthog.com")
    except Exception:
        return False


def _check_github_org_membership() -> bool | None:
    """Use ``gh api`` to check PostHog org membership. Returns None if gh is unavailable."""
    try:
        result = subprocess.run(
            ["gh", "api", "/user/memberships/orgs/PostHog", "--silent"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return None


def _is_posthog_dev() -> bool:
    """Return True if the current user is a PostHog GitHub org member.

    Caches the boolean for 30 days in the telemetry config. Falls back to a
    git-email-domain check when ``gh`` is unavailable or unauthenticated.
    """
    config = _load_config()
    cached = config.get("is_posthog_org_member")
    checked_at = config.get("org_check_timestamp", 0.0)

    if cached is not None and (time.time() - checked_at) < _POSTHOG_DEV_CACHE_TTL_SECONDS:
        return cached

    is_member = _check_github_org_membership()
    if is_member is None:
        is_member = _check_email_domain()

    config["is_posthog_org_member"] = is_member
    config["org_check_timestamp"] = time.time()
    _save_config(config)
    return is_member


def classify_command(command: str | None, argv: Sequence[str] = ()) -> CommandKind:
    """Bucket a hogli command by the kind of work it does, so verification loops can be counted.

    *argv* holds the arguments after the command name. ``hogli test`` dispatches on its
    paths, so a path the test runner hands to Playwright makes it an e2e run.
    """
    if not command:
        return "other"
    segments = command.split(":")
    prefix = segments[0]
    leaf = segments[-1]
    if command == "ci:preflight":
        return "verify-preflight"
    if command == "test:e2e" or (
        command == "test" and any(runs_on_playwright(arg) for arg in argv if not arg.startswith("-"))
    ):
        return "verify-e2e"
    if "typecheck" in leaf or "mypy" in leaf:
        return "verify-typecheck"
    if command not in _NOT_TESTS and (prefix == "test" or leaf == "test"):
        return "verify-test"
    if prefix in {"lint", "format"} or "lint" in segments or command in _LINT_COMMANDS:
        return "verify-lint"
    if prefix == "build" or leaf == "build":
        return "build"
    if prefix == "devbox":
        return "devbox"
    if command in _RUN_STACK_COMMANDS or prefix in {"start", "docker", "check"}:
        return "run-stack"
    return "other"


@dataclass(frozen=True)
class RecordedRun:
    session_id: str
    kind: str
    at: float


def is_rerun(runs: Sequence[RecordedRun], session_id: str, kind: str, now: float) -> bool:
    """Whether *kind* already ran in *session_id* within the rerun window before *now*."""
    return any(
        run.session_id == session_id and run.kind == kind and 0 <= now - run.at <= _RERUN_WINDOW_SECONDS for run in runs
    )


def _recent_runs(runs: Sequence[RecordedRun], now: float) -> list[RecordedRun]:
    recent = [run for run in runs if 0 <= now - run.at <= _RERUN_WINDOW_SECONDS]
    return recent[-_MAX_RECORDED_RUNS:]


@contextlib.contextmanager
def _state_lock() -> Iterator[None]:
    """Serialize the state read-modify-write across hogli processes.

    Gives up after a few milliseconds and runs unlocked, because a lost rerun record
    costs less than a delayed command.
    """
    handle = None
    try:
        _TELEMETRY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = _TELEMETRY_STATE_PATH.with_name(f"{_TELEMETRY_STATE_PATH.name}.lock").open("a")
        for attempt in range(_STATE_LOCK_ATTEMPTS):
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt < _STATE_LOCK_ATTEMPTS - 1:
                    time.sleep(_STATE_LOCK_RETRY_SECONDS)
    except Exception:
        pass
    try:
        yield
    finally:
        if handle is not None:
            handle.close()


def _load_state() -> dict[str, Any]:
    try:
        state = json.loads(_TELEMETRY_STATE_PATH.read_text())
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    """Write through a rename so a concurrent hogli process never reads a partial file."""
    try:
        _TELEMETRY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TELEMETRY_STATE_PATH.with_name(f"{_TELEMETRY_STATE_PATH.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(_TELEMETRY_STATE_PATH)
    except Exception:
        pass


def _parse_runs(raw: Any) -> list[RecordedRun]:
    runs: list[RecordedRun] = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            session_id, kind, at = entry
            runs.append(RecordedRun(session_id=str(session_id), kind=str(kind), at=float(at)))
        except Exception:
            continue
    return runs


def _proc_start_time(pid: int) -> str | None:
    """Start time of *pid* from ``/proc``, which tells apart two terminals that got the same pid."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # Field 2 is the command name and can contain spaces, so split after its closing paren.
        return stat.rsplit(")", 1)[1].split()[19]
    except Exception:
        return None


def _ps_start_time(pid: int) -> str | None:
    try:
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=1)
        started = result.stdout.strip()
        return started if result.returncode == 0 and started else None
    except Exception:
        return None


def _terminal_session_id(state: dict[str, Any], now: float) -> str | None:
    """Stable id for the terminal session, shared by every hogli call made in it.

    The session leader (the login shell, or the harness that spawned the shell) outlives
    each hogli process. Where ``/proc`` gives the leader start time cheaply, every call
    checks it, so a recycled leader pid gets a new id. Elsewhere the cache in *state*
    keeps the ``ps`` call off most invocations.
    """
    try:
        leader = os.getsid(0)
    except Exception:
        return None
    started = _proc_start_time(leader)
    cache = state.get("terminal_sessions")
    cache = cache if isinstance(cache, dict) else {}
    cached = cache.get(str(leader))
    if (
        started is None
        and isinstance(cached, dict)
        and now - float(cached.get("seen", 0)) < _TERMINAL_SESSION_TTL_SECONDS
    ):
        session_id = str(cached.get("id"))
    else:
        started = started or _ps_start_time(leader)
        if started is None:
            return None
        digest = hashlib.sha256(f"{socket.gethostname()}|{leader}|{started}".encode()).hexdigest()
        session_id = f"term-{digest[:16]}"
    cache[str(leader)] = {"id": session_id, "seen": now}
    newest = sorted(cache.items(), key=lambda item: float(item[1].get("seen", 0)), reverse=True)
    state["terminal_sessions"] = dict(newest[:_MAX_CACHED_TERMINAL_SESSIONS])
    return session_id


def _agent_session_id(state: dict[str, Any]) -> str | None:
    for var in _AGENT_SESSION_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            salt = state.get("session_salt")
            if not isinstance(salt, str) or not salt:
                salt = secrets.token_hex(16)
                state["session_salt"] = salt
            digest = hashlib.sha256(f"{salt}|{value}".encode()).hexdigest()
            return f"agent-{digest[:16]}"
    return None


@functools.cache
def _session_properties(command: str | None) -> dict[str, Any]:
    """Session, command kind, and rerun flag for this invocation.

    Cached per process, so command_started, command_completed and ci_preflight_run
    report the same values and the run is recorded once. A second record would make
    the invocation count as its own rerun.
    """
    kind = classify_command(command, sys.argv[2:])
    props: dict[str, Any] = {"command_kind": kind, "session_id": None, "session_id_source": None, "is_rerun": None}
    try:
        now = time.time()
        with _state_lock():
            state = _load_state()
            session_id = _agent_session_id(state)
            source = "agent" if session_id else None
            if session_id is None:
                session_id = _terminal_session_id(state, now)
                source = "terminal"
            if session_id is None:
                return props
            runs = _parse_runs(state.get("runs"))
            props.update(
                session_id=session_id, session_id_source=source, is_rerun=is_rerun(runs, session_id, kind, now)
            )
            recorded = _recent_runs([*runs, RecordedRun(session_id=session_id, kind=kind, at=now)], now)
            state["runs"] = [[run.session_id, run.kind, run.at] for run in recorded]
            _save_state(state)
    except Exception:
        pass
    return props


def _pr_number() -> int | None:
    """PR number from the environment only, because a ``gh`` call on every command is too slow."""
    match = _GITHUB_PULL_REF.match(os.environ.get("GITHUB_REF", ""))
    if match:
        return int(match.group(1))
    for var in _PR_NUMBER_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if value.isdigit():
            return int(value)
    return None


def _posthog_telemetry_properties(command: str | None = None) -> dict[str, Any]:
    # Agent-driven traffic (e.g. skills running metabase:query) otherwise
    # swamps human usage stats.
    agent = _detect_agent()
    return {
        "actor": _detect_actor(agent),
        "agent": agent,
        "environment": _detect_environment(),
        "git_hook": _declared("HOGLI_GIT_HOOK") or None,
        "has_devenv_config": (REPO_ROOT / ".posthog" / ".generated" / "mprocs.yaml").exists(),
        "in_flox": os.environ.get("FLOX_ENV") is not None,
        "is_agent": agent is not None,
        "is_worktree": (REPO_ROOT / ".git").is_file(),
        "is_posthog_dev": _is_posthog_dev(),
        "process_manager": _infer_process_manager(command),
        "git_branch": _git_branch(),
        "pr_number": _pr_number(),
        **_session_properties(command),
        **_repo_commit_properties(),
    }


register_telemetry_properties(_posthog_telemetry_properties)

# Set at import, because an environment write is unsafe once the telemetry send thread runs.
if _detect_actor(_detect_agent()) == "human":
    os.environ[_ACTOR_ENV_VAR] = "human"
