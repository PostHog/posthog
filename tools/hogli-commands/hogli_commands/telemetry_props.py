"""PostHog-specific telemetry property hooks.

Registers a hook that enriches every ``command_started`` / ``command_completed``
event with PostHog-developer context (process manager, devenv state, org
membership, etc.). Imports here are stdlib only — keep it light, this loads at
boot.
"""

from __future__ import annotations

import os
import sys
import time
import subprocess
import configparser
from pathlib import Path
from typing import Any

from hogli.hooks import register_telemetry_properties
from hogli.manifest import REPO_ROOT
from hogli.telemetry import _load_config, _save_config

_POSTHOG_DEV_CACHE_TTL_SECONDS = 30 * 86400  # 30 days


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
    return {
        "has_devenv_config": (REPO_ROOT / ".posthog" / ".generated" / "mprocs.yaml").exists(),
        "in_flox": os.environ.get("FLOX_ENV") is not None,
        "is_worktree": (REPO_ROOT / ".git").is_file(),
        "is_posthog_dev": _is_posthog_dev(),
        "process_manager": _infer_process_manager(command),
    }


register_telemetry_properties(_posthog_telemetry_properties)
