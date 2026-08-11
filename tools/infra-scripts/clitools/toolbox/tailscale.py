#!/usr/bin/env python3
"""Tailscale connectivity preflight for the toolbox CLI.

The toolbox-capable Kubernetes API endpoints are only reachable over the
PostHog tailnet, so a disconnected Tailscale surfaces as opaque kubectl
timeouts. Checking up front turns that into an actionable message.

Adapted from hogli's devbox preflight (hogli_commands/devbox/coder.py); this
script is standalone and stdlib-only, so it cannot import that package.
"""

import os
import sys
import json
import shutil
import subprocess
from typing import Any

# macOS ships the CLI inside the app bundle, so it is often not on PATH.
MACOS_TAILSCALE_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
TAILSCALE_RUNBOOK_URL = "https://runbooks.posthog.com/vpn/#tailscale"
SKIP_CHECK_ENV_VAR = "TOOLBOX_SKIP_TAILSCALE_CHECK"
STATUS_TIMEOUT_SECONDS = 10

# Health warning emitted by `tailscale status` when peers advertise subnet
# routes but the local node has `--accept-routes` disabled. The cluster
# endpoints sit behind subnet routers, so DNS resolves but traffic blackholes.
ACCEPT_ROUTES_HEALTH_FRAGMENT = "--accept-routes is false"


def resolve_tailscale() -> str | None:
    """Return the path to the tailscale CLI, checking PATH then the macOS app bundle."""
    if path := shutil.which("tailscale"):
        return path
    if sys.platform == "darwin" and os.path.isfile(MACOS_TAILSCALE_CLI):
        return MACOS_TAILSCALE_CLI
    return None


def _tailscale_env(tailscale_path: str) -> dict[str, str] | None:
    """Return extra env vars needed when invoking the macOS app bundle CLI."""
    if tailscale_path == MACOS_TAILSCALE_CLI:
        return {**os.environ, "TAILSCALE_BE_CLI": "1"}
    return None


def get_tailscale_status() -> dict[str, Any] | None:
    """Return parsed `tailscale status --json` output, or None when unavailable."""
    tailscale_path = resolve_tailscale()
    if not tailscale_path:
        return None
    try:
        result = subprocess.run(
            [tailscale_path, "status", "--json"],
            capture_output=True,
            text=True,
            env=_tailscale_env(tailscale_path),
            timeout=STATUS_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _install_hint() -> str:
    if sys.platform == "darwin":
        return "Install it: brew install --cask tailscale (or via the Mac App Store)."
    if sys.platform.startswith("linux"):
        return "Install it: curl -fsSL https://tailscale.com/install.sh | sh"
    return "Install it from https://tailscale.com/download."


def _connect_hint() -> str:
    if sys.platform == "darwin":
        return "Open the Tailscale app and sign in with your PostHog Google account."
    return "Run `sudo tailscale up` and complete the SSO flow with your PostHog Google account."


def _cli_missing_on_macos() -> bool:
    """Return whether macOS has the Tailscale app but no CLI on PATH."""
    return sys.platform == "darwin" and shutil.which("tailscale") is None and os.path.isfile(MACOS_TAILSCALE_CLI)


def warn_if_subnet_routes_rejected(status: dict[str, Any] | None) -> None:
    """Warn when the node rejects advertised subnet routes; cluster traffic needs them."""
    health = (status or {}).get("Health") or []
    if not any(ACCEPT_ROUTES_HEALTH_FRAGMENT in (message or "") for message in health):
        return
    fix = "tailscale set --accept-routes" if sys.platform == "darwin" else "sudo tailscale set --accept-routes"
    print("⚠️ Tailscale is not accepting subnet routes, so the cluster may be unreachable.")  # noqa: T201
    print(f"   Fix it with: {fix}")  # noqa: T201


def ensure_tailscale_connected() -> None:
    """Exit with guidance when the host is not connected to the PostHog tailnet.

    Distinguishes not-installed from installed-but-not-running, with the fix
    for each, plus a symlink hint on macOS when the CLI only exists inside the
    app bundle. Set TOOLBOX_SKIP_TAILSCALE_CHECK=1 to skip the check entirely,
    for hosts that reach the cluster some other way.
    """
    if os.environ.get(SKIP_CHECK_ENV_VAR):
        return

    status = get_tailscale_status()
    if status and status.get("BackendState") == "Running":
        warn_if_subnet_routes_rejected(status)
        return

    if not resolve_tailscale():
        print("❌ Tailscale is not installed, and the toolbox needs the PostHog tailnet to reach the cluster.")  # noqa: T201
        print(f"   {_install_hint()}")  # noqa: T201
        print(f"   See {TAILSCALE_RUNBOOK_URL} for joining the PostHog tailnet, then rerun the toolbox.")  # noqa: T201
        print(f"   Connected through something else? Set {SKIP_CHECK_ENV_VAR}=1 to skip this check.")  # noqa: T201
        sys.exit(1)

    print("❌ Tailscale is not connected, and the toolbox needs the PostHog tailnet to reach the cluster.")  # noqa: T201
    print(f"   {_connect_hint()}")  # noqa: T201
    if _cli_missing_on_macos():
        print("   To use the tailscale CLI from your shell, symlink it once:")  # noqa: T201
        print(f"     sudo ln -sfn {MACOS_TAILSCALE_CLI} /usr/local/bin/tailscale")  # noqa: T201
    print(f"   See {TAILSCALE_RUNBOOK_URL} if you have not yet joined the PostHog tailnet, then rerun the toolbox.")  # noqa: T201
    print(f"   Connected through something else? Set {SKIP_CHECK_ENV_VAR}=1 to skip this check.")  # noqa: T201
    sys.exit(1)
