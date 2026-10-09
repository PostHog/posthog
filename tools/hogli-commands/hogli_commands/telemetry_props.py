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
import time
import functools
import subprocess
import configparser
from pathlib import Path
from typing import Any, Literal

from hogli.hooks import register_telemetry_properties
from hogli.manifest import REPO_ROOT
from hogli.telemetry import _load_config, _save_config, is_ci

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
# marker must win over theirs. A marker belongs here only if the harness sets
# it in agent-spawned shells alone. One that a person's own terminal also
# carries (ZED_TERM, CURSOR_TRACE_ID) would count that person as an agent.
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

# Cross-tool convention for a harness to name itself, listed as standard by
# https://huggingface.co/api/agent-harnesses. Read after the markers above,
# because each harness formats the value differently and a marker gives one
# stable name. A harness that sets neither can export HOGLI_AGENT instead.
_STANDARD_AGENT_ENV_VARS = ("AI_AGENT", "AGENT")

_ACTOR_ENV_VAR = "HOGLI_ACTOR"


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
            # Some harnesses append a version (`name@1.2`, `name_1-2_agent`),
            # which would split one harness into a telemetry value per release.
            name = re.split(r"\s*[@_]\d", declared, maxsplit=1)[0]
            # A harness can set the variable as a bare flag (`AGENT=1`) without naming itself.
            return "unknown" if name in {"", "1", "true"} else name
    return None


def _detect_actor(agent: str | None) -> Literal["agent", "human", "unknown"]:
    """Classify who drives this invocation.

    A run counts as human only on positive evidence, which is a terminal on a
    standard stream. A run with no agent name and no terminal is unknown,
    because an unmarked harness, a GUI git client, and a script look the same.
    """
    if agent is not None:
        return "agent"
    # A nested hogli command runs with captured streams, so the outermost
    # invocation passes its verdict down through the environment.
    if _declared(_ACTOR_ENV_VAR) == "human":
        return "human"
    # Any stream, not stdin alone: git pipes the pushed refs into the stdin of
    # a pre-push hook, so a person's push has a terminal only on stdout/stderr.
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


def _posthog_telemetry_properties(command: str | None = None) -> dict[str, Any]:
    # Agent-driven traffic (e.g. skills running metabase:query) otherwise
    # swamps human usage stats.
    agent = _detect_agent()
    actor = _detect_actor(agent)
    # The first call runs at command start, before the telemetry send thread
    # exists. setdefault keeps every later call read-only, because a write to
    # the environment while that thread runs is unsafe.
    os.environ.setdefault(_ACTOR_ENV_VAR, actor)
    return {
        "actor": actor,
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
        **_repo_commit_properties(),
    }


register_telemetry_properties(_posthog_telemetry_properties)
