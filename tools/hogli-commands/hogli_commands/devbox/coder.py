"""Coder CLI wrapper for devbox management.

All subprocess interactions with the Coder CLI are isolated here.
"""

from __future__ import annotations

import io
import os
import re
import csv
import sys
import json
import time
import shlex
import base64
import shutil
import socket
import functools
import itertools
import threading
import subprocess
import webbrowser
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import click
import requests
from hogli import telemetry
from hogli.cli import send_completion_before_exec
from hogli.manifest import load_manifest

_MACOS_TAILSCALE_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
_TAILSCALE_RUNBOOK_URL = "https://wiki.posthog.com/access/vpn#which-tailnet"
# The only tailnet that routes to devboxes. PostHog also runs per-environment
# tailnets (dev, prod-us, prod-eu, internal) for CI runners and subnet routers;
# none of them reach the Coder control plane. Tailscale only asks which tailnet
# to join at first sign-in, so someone who picked wrong there stays wrong
# silently and forever -- worth naming as its own diagnosis.
EXPECTED_TAILNET = "posthog.com"
DEFAULT_TEMPLATE = "posthog-linux"
# Newer coder versions added an interactive "Select a preset" prompt to `coder
# create` that `--yes` does not bypass. Callers must always forward `--preset`
# with a concrete value -- either a preset the template defines, or the literal
# NO_PRESET sentinel below.
NO_PRESET = "none"
# Opt out of presets by default so a vanilla `hogli devbox:start` never claims
# from a prebuild warm pool (a Coder premium feature). Pass `--preset <name>` to
# select a template preset explicitly where one is defined.
DEFAULT_PRESET = NO_PRESET
# Coder applies the active template version only when a workspace starts, never
# to a running one, so template fixes reach a box without rebuilding it mid-run.
AUTOMATIC_UPDATES_ARGS = ("--automatic-updates", "always")
BREW_PACKAGE = "coder/coder/coder"
RUNTIME_SETUP_HINT = "Run `hogli devbox:setup`."
_MANAGED_CODER_DIR = Path.home() / ".hogli" / "bin"
GIT_NAME_PARAMETER = "git_name"
GIT_EMAIL_PARAMETER = "git_email"
DOTFILES_URI_PARAMETER = "dotfiles_uri"
DOTFILES_BRANCH_PARAMETER = "dotfiles_branch"
JETBRAINS_IDES_PARAMETER = "jetbrains_ides"

# Opt-in: bring the PostHog app (the `hogli up` dev stack) up in the
# background on every workspace start. Mutable and sticky on the workspace, so
# it stays in effect for future starts until explicitly flipped off. On
# template versions that don't define it yet, the retry shim drops it with a
# visible warning.
AUTO_START_APP_PARAMETER = "auto_start_app"

# Create-time region selector. The template defines `workspace_region` with a
# us-east-1 default; eu-central-1 became a valid option when the EU
# infrastructure went live. The value is immutable after creation, so it is
# forwarded on `coder create` only, never on `coder update`. Coder carries an
# immutable parameter's value forward on its
# own during an update and *rejects* any explicit `--parameter
# workspace_region=` with "parameter is immutable and cannot be updated". The
# option-change re-prompt that no flag can bypass only applies to *mutable*
# parameters, so forwarding the region here breaks every resume instead of
# suppressing a picker. Valid values match the template contract exactly.
WORKSPACE_REGION_PARAMETER = "workspace_region"
DISK_SIZE_PARAMETER = "disk_size"
REGIONS = ("us-east-1", "eu-central-1")
DEFAULT_REGION = REGIONS[0]

# Immutable, create-time parameter consumed by `devbox:clone`: the EC2 instance
# of the source devbox. The template images that instance server-side and boots
# the new box from the capture, so the duplicate comes up with the source's full
# disk state instead of a blank golden AMI. Empty everywhere else.
CLONE_SOURCE_PARAMETER = "clone_source_instance_id"
# Keys of the workspace metadata items the template publishes back.
REGION_METADATA_KEY = "region"
DISK_METADATA_KEY = "disk"
# Workspace-name suffix per region. us-east-1 is the historical default and
# carries no suffix, so existing workspace names stay unchanged. Non-default
# regions append `-{suffix}` at the end of the name so that a single user can
# own one default workspace per region (`devbox-rauln` + `devbox-rauln-eu`)
# without collision. Labels that conflict with a region suffix are rejected up
# front -- see `_RESERVED_LABEL_SUFFIXES`.
REGION_NAME_SUFFIXES: dict[str, str] = {
    "us-east-1": "",
    "eu-central-1": "eu",
}
_RESERVED_LABEL_SUFFIXES: tuple[str, ...] = tuple(s for s in REGION_NAME_SUFFIXES.values() if s)

# Per-user Coder secret holding the SSH public key used to sign commits inside
# workspaces. Injected as the POSTHOG_GIT_SIGNING_KEY env var on every workspace
# start; the workspace template reads it to populate user.signingkey. The
# matching private key never leaves 1Password. The `GIT_` prefix is reserved by
# Coder, so the workspace-side env name cannot start with it.
GIT_SIGNING_KEY_SECRET = "POSTHOG_GIT_SIGNING_KEY"


# Coder rejects --parameter values for keys the chosen template does not
# define, with this exact message: `parameter "X" is not present in the
# template`. The check happens client-side before any provisioning starts,
# so a failed call is cheap to retry. _run_with_param_retry drops the
# offending key from the candidate set and retries on this match. Anchored
# to the start of a line so a user-supplied parameter value containing this
# phrase cannot trick the matcher.
_PARAM_NOT_PRESENT_RE = re.compile(r'^parameter "([^"]+)" is not present', re.MULTILINE)

_STEP_RE = re.compile(r"^==>.*?(\w[\w ]+)")
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_WORKSPACE_PREFIX = "devbox"


class CoderUserInfo(dict[str, str]):
    """Normalized subset of Coder user fields used by hogli."""


def _fail(message: str, *, cause: str | None = None) -> NoReturn:
    """Print a short actionable error and exit.

    ``cause`` is a stable slug recorded on the command's telemetry event.
    Without it every distinct failure reads as one undifferentiated error.
    """
    click.echo(click.style(message, fg="red"))
    if cause:
        telemetry.add_command_properties(devbox_failure_cause=cause)
    raise SystemExit(1)


def get_coder_url() -> str:
    """Resolve the configured Coder deployment URL."""
    if url := os.environ.get("HOGLI_DEVBOX_CODER_URL"):
        return url

    if url := os.environ.get("CODER_URL"):
        return url

    manifest = load_manifest()
    metadata = manifest.get("metadata", {})
    devbox_metadata = metadata.get("devbox", {})
    if isinstance(devbox_metadata, dict) and isinstance(devbox_metadata.get("coder_url"), str):
        return devbox_metadata["coder_url"]

    raise RuntimeError("Missing `metadata.devbox.coder_url` in hogli.yaml.")


def _normalize_version(version: str) -> str:
    """Strip leading ``v`` and semver build metadata (``+hash``)."""
    return version.lstrip("v").split("+")[0]


# Coder server version that introduced user secrets (Early Access).
USER_SECRETS_MIN_VERSION = (2, 33)


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse a normalized semver string into an int tuple for ordered comparison.

    Trailing pre-release segments (``-rc1``) are dropped from each component so
    ``2.33.0-rc1`` compares equal to ``2.33.0`` for the gate we care about.
    """
    parts: list[int] = []
    for segment in version.split("."):
        digits = segment.split("-", 1)[0]
        if not digits.isdigit():
            break
        parts.append(int(digits))
    return tuple(parts)


def server_supports_user_secrets() -> bool:
    """Return whether the configured Coder server is >= 2.33.

    Returns ``False`` (graceful) if the server version cannot be determined,
    so callers can skip secret-related steps without aborting setup.
    """
    try:
        version = get_server_version()
    except RuntimeError:
        return False
    return _version_tuple(version) >= USER_SECRETS_MIN_VERSION


def get_server_version() -> str:
    """Query the Coder deployment for its running version."""
    if version := os.environ.get("HOGLI_DEVBOX_CODER_VERSION"):
        return version

    coder_url = get_coder_url()
    try:
        resp = requests.get(f"{coder_url}/api/v2/buildinfo", timeout=5)
        data = resp.json()
        raw = data.get("version", "")
        if raw:
            return _normalize_version(raw)
    except Exception:
        pass

    raise RuntimeError(f"Could not determine server version from {coder_url}/api/v2/buildinfo.")


def _coder_bin() -> str:
    """Return the path to the hogli-managed coder binary, falling back to PATH."""
    managed = _MANAGED_CODER_DIR / "coder"
    if managed.is_file():
        return str(managed)
    return shutil.which("coder") or "coder"


def _resolve_coder(args: list[str]) -> list[str]:
    """Replace a leading ``"coder"`` arg with the managed binary path."""
    if args and args[0] == "coder":
        return [_coder_bin(), *args[1:]]
    return args


def _run(
    args: list[str], *, capture_output: bool = False, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with consistent text handling."""
    return subprocess.run(_resolve_coder(args), capture_output=capture_output, text=True, timeout=timeout)


def _execvp(file: str, args: list[str]) -> NoReturn:
    """Replace the current process, sending hogli's command telemetry first."""
    send_completion_before_exec()
    os.execvp(file, args)


def _run_or_exit(args: list[str]) -> None:
    """Replace the current process with a Coder command or exit with its status."""
    resolved = _resolve_coder(args)
    coder_path = resolved[0] if resolved else shutil.which("coder")
    if coder_path:
        _execvp(coder_path, resolved)

    sys.exit(_run(args).returncode)


def _run_build(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a Coder build command with a spinner.

    In normal mode, shows a single-line spinner that updates with each
    build step. In verbose mode, streams all output including Terraform
    internals. On failure the full captured output is always printed.
    """
    proc = subprocess.Popen(_resolve_coder(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    captured: list[str] = []
    if proc.stdout is None:
        raise RuntimeError("Popen stdout pipe was not opened")

    if verbose:
        for line in proc.stdout:
            captured.append(line)
            click.echo(line, nl=False)
    else:
        is_tty = sys.stderr.isatty()
        status = "Starting"
        stop_event = threading.Event()
        frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])

        def _spin() -> None:
            while not stop_event.is_set():
                if is_tty:
                    click.echo(f"\r  {next(frames)} {status}...\033[K", nl=False, err=True)
                stop_event.wait(0.08)
            if is_tty:
                click.echo(f"\r  {status}\033[K", err=True)

        spinner = threading.Thread(target=_spin, daemon=True)
        spinner.start()

        for line in proc.stdout:
            captured.append(line)
            m = _STEP_RE.match(line)
            if m:
                status = m.group(1).strip()

        stop_event.set()
        spinner.join()

    returncode = proc.wait()

    if returncode != 0 and not verbose:
        click.echo()
        click.echo(click.style("Build failed. Full output:", fg="red"))
        for line in captured:
            click.echo(line, nl=False)

    return subprocess.CompletedProcess(args, returncode, "".join(captured), "")


def _append_parameter_flags(args: list[str], parameters: dict[str, str]) -> list[str]:
    """Append `--parameter key=value` flags for each entry in ``parameters``."""
    out = list(args)
    for key, value in parameters.items():
        out += ["--parameter", f"{key}={value}"]
    return out


def _run_with_param_retry(
    base_args: list[str],
    parameters: dict[str, str],
    *,
    verbose: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a Coder build command, dropping unknown parameters and retrying.

    Coder validates ``--parameter`` keys client-side before any provisioning
    starts, so retrying after a `parameter "X" is not present in the
    template` error is cheap and safe. All other failures bubble up
    unchanged, so `coder create` callers never have to know which keys the
    chosen template happens to accept.
    """
    remaining = dict(parameters)
    while True:
        result = _run_build(_append_parameter_flags(base_args, remaining), verbose=verbose)
        if result.returncode == 0:
            return result
        match = _PARAM_NOT_PRESENT_RE.search(result.stdout or "")
        if not match or match.group(1) not in remaining:
            return result
        dropped = match.group(1)
        click.echo(click.style(f"Template doesn't accept '{dropped}', retrying without it.", fg="yellow"))
        del remaining[dropped]


# AWS error code when an availability zone has no free capacity for the requested instance type.
_CAPACITY_ERROR = "InsufficientInstanceCapacity"


class CapacityShortage(SystemExit):
    """A build failed because AWS had no capacity for the box's instance type in its zone."""


def _exit_for_failed_build(returncode: int, output: str) -> NoReturn:
    if _CAPACITY_ERROR in output:
        raise CapacityShortage(returncode or 1)
    raise SystemExit(returncode or 1)


def _resolve_tailscale() -> str | None:
    """Return path to the tailscale CLI, checking PATH then the macOS app bundle."""
    if path := shutil.which("tailscale"):
        return path
    if sys.platform == "darwin" and os.path.isfile(_MACOS_TAILSCALE_CLI):
        return _MACOS_TAILSCALE_CLI
    return None


def _tailscale_env(tailscale_path: str) -> dict[str, str] | None:
    """Return extra env vars needed when invoking the macOS app bundle CLI."""
    if tailscale_path == _MACOS_TAILSCALE_CLI:
        return {**os.environ, "TAILSCALE_BE_CLI": "1"}
    return None


def _tailscale_status() -> dict[str, Any] | None:
    """Return parsed `tailscale status --json` output when available."""
    tailscale_path = _resolve_tailscale()
    if not tailscale_path:
        return None

    result = subprocess.run(
        [tailscale_path, "status", "--json"],
        capture_output=True,
        text=True,
        env=_tailscale_env(tailscale_path),
    )
    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _backend_running(status: dict[str, Any] | None) -> bool:
    """Return whether a `tailscale status --json` blob reports a live backend."""
    return bool(status and status.get("BackendState") == "Running")


def _tailnet_name(status: dict[str, Any] | None) -> str | None:
    """Return the active tailnet's name from a `tailscale status --json` blob."""
    current_tailnet = (status or {}).get("CurrentTailnet")
    if not isinstance(current_tailnet, dict):
        return None
    name = current_tailnet.get("Name")
    return name if isinstance(name, str) and name else None


def tailscale_connected() -> bool:
    """Check if Tailscale is running and connected."""
    return _backend_running(_tailscale_status())


def tailscale_state() -> tuple[bool, str | None]:
    """Return ``(connected, tailnet name)`` from a single `tailscale status` probe.

    Bundled because each `_tailscale_status()` call is a subprocess, and the
    two facts are always reported next to each other. The name is ``None``
    when Tailscale is down or the blob does not name a tailnet.
    """
    status = _tailscale_status()
    return _backend_running(status), _tailnet_name(status)


def _tailscale_install_hint() -> str:
    """Return the platform-specific install command for Tailscale.

    On macOS, the CLI ships inside ``Tailscale.app`` — engineers commonly
    install the GUI and never realize there is also a CLI to put on PATH.
    Recommending the cask install handles both at once; the App Store build
    is mentioned as a fallback because some employees install it that way.
    """
    if sys.platform == "darwin":
        return "Install: `brew install --cask tailscale` (or via the Mac App Store)."
    if sys.platform.startswith("linux"):
        return "Install: `curl -fsSL https://tailscale.com/install.sh | sh`."
    return "Install Tailscale from https://tailscale.com/download."


def _tailscale_connect_hint() -> str:
    """Return the platform-specific command for joining a tailnet."""
    if sys.platform == "darwin":
        return "Open the Tailscale app and sign in with your PostHog Google account."
    return "Run `sudo tailscale up` and complete the SSO flow with your PostHog Google account."


def _tailscale_cli_missing_on_macos() -> bool:
    """Return whether macOS has the Tailscale app but no CLI on PATH."""
    return sys.platform == "darwin" and shutil.which("tailscale") is None and os.path.isfile(_MACOS_TAILSCALE_CLI)


def _tailnet_switch_hint() -> str:
    """Return the command for moving to the PostHog tailnet.

    On macOS the GUI is how most people signed in, and `tailscale` is often
    not on PATH at all -- so name the app-bundle CLI there instead.
    """
    cli = _MACOS_TAILSCALE_CLI if _tailscale_cli_missing_on_macos() else "tailscale"
    return (
        f"`{cli} switch {EXPECTED_TAILNET}` if you have signed into it before, "
        f"otherwise `{cli} logout && {cli} login` and pick {EXPECTED_TAILNET} "
        "at the tailnet picker (in the GUI: Add account, sign in, select "
        f"{EXPECTED_TAILNET})."
    )


def ensure_tailscale_connected(setup_hint: str = RUNTIME_SETUP_HINT) -> None:
    """Fail fast when the host is not connected to a Tailscale tailnet.

    Reports three distinct states with the action that fixes each: not
    installed (give the install command), installed but not running (give
    the connect command), and a special macOS path where the GUI is present
    but the CLI is hidden inside the app bundle (point to the symlink).
    """
    if tailscale_connected():
        return

    if not _resolve_tailscale():
        _fail(
            "Tailscale is not installed.\n"
            f"  {_tailscale_install_hint()}\n"
            f"  See {_TAILSCALE_RUNBOOK_URL} for joining the PostHog tailnet.\n"
            f"  Then {setup_hint}",
            cause="tailscale_not_installed",
        )

    # CLI is resolvable, but the daemon is not running -- the user needs to
    # sign in (a fresh install) or bring the agent back up (it was stopped).
    if _tailscale_cli_missing_on_macos():
        # `_resolve_tailscale()` succeeded via the bundled CLI, but `tailscale`
        # is not on PATH. This trips engineers who try to follow the printed
        # `tailscale status` hint and get "command not found".
        _fail(
            "Tailscale is installed but not connected, and the `tailscale` CLI is not on your PATH.\n"
            f"  {_tailscale_connect_hint()}\n"
            "  To use the CLI from your shell, symlink it once:\n"
            f"    sudo ln -sfn {_MACOS_TAILSCALE_CLI} /usr/local/bin/tailscale\n"
            f"  See {_TAILSCALE_RUNBOOK_URL} if you have not yet been added to the tailnet.\n"
            f"  Then {setup_hint}",
            cause="tailscale_not_connected_cli_missing",
        )

    _fail(
        "Tailscale is installed but not connected.\n"
        f"  {_tailscale_connect_hint()}\n"
        f"  See {_TAILSCALE_RUNBOOK_URL} if you have not yet been added to the tailnet.\n"
        f"  Then {setup_hint}",
        cause="tailscale_not_connected",
    )


# Health warning emitted by `tailscale status` when peers advertise subnet routes
# but the local node has `--accept-routes` disabled. The Coder ALB lives behind
# a VPC subnet router, so DNS resolves but traffic blackholes without this.
_ACCEPT_ROUTES_HEALTH_FRAGMENT = "--accept-routes is false"


def _tailscale_routes_accepted() -> bool:
    """Return whether the local node accepts advertised subnet routes."""
    status = _tailscale_status()
    if not status:
        return True
    health = status.get("Health") or []
    return not any(_ACCEPT_ROUTES_HEALTH_FRAGMENT in (msg or "") for msg in health)


def ensure_tailscale_routes_accepted() -> bool:
    """Enable Tailscale subnet route acceptance when peers advertise routes.

    Returns whether this call enabled it.
    """
    if _tailscale_routes_accepted():
        return False

    # The fix below is silent, so without this the number of hosts that land
    # here stays unknowable.
    telemetry.add_command_properties(devbox_routes_were_off=True)

    tailscale_path = _resolve_tailscale()
    if not tailscale_path:
        return False

    click.echo("Enabling Tailscale subnet routes (required for devbox access)...")
    cmd = [tailscale_path, "set", "--accept-routes"]
    if sys.platform != "darwin" and hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", *cmd]

    result = subprocess.run(cmd, env=_tailscale_env(tailscale_path))
    if result.returncode != 0:
        manual = "tailscale set --accept-routes" if sys.platform == "darwin" else "sudo tailscale set --accept-routes"
        _fail(
            f"Failed to enable Tailscale subnet routes. Run manually: {manual}",
            cause="accept_routes_failed",
        )
    return True


def _probe_coder(timeout: float = 5.0) -> requests.Response | None:
    """Return the response from /api/v2/buildinfo, or None when no response arrives."""
    coder_url = get_coder_url()
    try:
        return requests.get(f"{coder_url}/api/v2/buildinfo", timeout=timeout)
    except requests.RequestException:
        return None


def coder_reachable(timeout: float = 5.0) -> bool:
    """Return whether the Coder deployment responds on /api/v2/buildinfo."""
    resp = _probe_coder(timeout)
    return resp is not None and resp.ok


@dataclass(frozen=True)
class CoderReachabilityDiagnosis:
    """Why the Coder deployment is unreachable, with a single actionable next step.

    The structured form lets the caller present one concrete cause and one
    fix rather than a list of commands the user has to interpret. ``facts``
    is a short list of diagnostic data (tailnet name, resolved IP, peer
    health) that is safe to share verbatim when asking for help.

    ``code`` is the same cause as a stable slug. ``cause`` interpolates
    hostnames and peer names, so it cannot be grouped on.
    """

    code: str
    cause: str
    next_step: str
    facts: list[str]


def _resolve_host_ip(host: str) -> str | None:
    """Resolve a hostname to a single IP, or ``None`` if resolution fails.

    Uses the OS resolver so MagicDNS lookups via Tailscale (or split-DNS
    routes through the tailnet) are honored just as they would be for the
    actual HTTPS probe. We swallow OSError because every resolver failure
    mode maps to the same "DNS failed" branch downstream.
    """
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def _tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """Return whether a TCP handshake to ``(host, port)`` completes."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _diagnose_unreachable_coder() -> CoderReachabilityDiagnosis:
    """Diagnose why the Coder deployment is not reachable.

    Probes (in order) DNS resolution, TCP reachability on 443, and the
    Tailscale peer / route topology, picking the most specific cause and
    pairing it with a concrete next step. Returns the diagnosis instead of
    printing it so callers control formatting and tests can assert against
    structured fields.
    """
    coder_url = get_coder_url()
    host = urllib.parse.urlparse(coder_url).hostname or coder_url
    facts: list[str] = [f"Coder URL: {coder_url}"]

    status = _tailscale_status()
    tailnet_name: str | None = None
    if status:
        tailnet_name = _tailnet_name(status)
        facts.append(f"Tailscale tailnet: {tailnet_name or '<unknown>'}")
    else:
        facts.append("Tailscale status: unavailable")

    # Checked before DNS and TCP because every downstream probe fails the same
    # way from the wrong tailnet, and their fixes (MagicDNS, the ACL grant)
    # would all be red herrings.
    if tailnet_name is not None and tailnet_name != EXPECTED_TAILNET:
        return CoderReachabilityDiagnosis(
            code="wrong_tailnet",
            cause=f"Signed into the '{tailnet_name}' tailnet, not '{EXPECTED_TAILNET}'.",
            next_step=(
                f"Devboxes only exist on '{EXPECTED_TAILNET}' — the other tailnets are for CI "
                f"runners and subnet routers. Switch: {_tailnet_switch_hint()} "
                f"Details: {_TAILSCALE_RUNBOOK_URL}"
            ),
            facts=facts,
        )

    resolved_ip = _resolve_host_ip(host)
    if resolved_ip is None:
        facts.append(f"DNS for {host}: failed")
        return CoderReachabilityDiagnosis(
            code="dns_lookup_failed",
            cause=f"DNS lookup for {host} failed.",
            next_step=(
                "MagicDNS is probably off — turn on 'Use Tailscale DNS' in the "
                "client, or run `sudo tailscale up --accept-dns`. If it is "
                "already on, a stale router/ISP resolver is the usual culprit: "
                "add 8.8.8.8 or 1.1.1.1 to this machine's DNS settings. Do not "
                "reach for an exit node — devboxes are reached as tailnet peers, "
                "so it only slows everything down and hides the real cause."
            ),
            facts=facts,
        )
    facts.append(f"DNS for {host}: {resolved_ip}")

    if _tcp_reachable(host, 443):
        facts.append(f"TCP {host}:443: open")
        return CoderReachabilityDiagnosis(
            code="https_probe_failed",
            cause=f"TCP to {host}:443 works but the HTTPS probe failed.",
            next_step=(
                "The Coder deployment may be restarting, or your system clock "
                "is off (causing TLS to reject the cert). Check the time, then "
                "retry in a minute."
            ),
            facts=facts,
        )
    facts.append(f"TCP {host}:443: blocked / timed out")

    return _diagnose_blocked_route(status, facts)


def _diagnose_blocked_route(
    status: dict[str, Any] | None,
    facts: list[str],
) -> CoderReachabilityDiagnosis:
    """Pick a cause when DNS resolves but TCP to the Coder ALB is blocked.

    Walks the Tailscale peer map looking for subnet routers. Cases handled,
    in priority order:

    1. No peer advertises any subnet route — usually means the host is on
       the wrong tailnet (e.g. personal account) or has not been added to
       the PostHog tailnet yet.
    2. Routers exist but none are online — the relay is bouncing; waiting
       is the only fix.
    3. A router is online — Tailscale ACLs or a local VPN is intercepting.
    """
    peers = (status or {}).get("Peer") or {}
    routers = [p for p in peers.values() if isinstance(p, dict) and p.get("PrimaryRoutes")]
    online_routers = [p for p in routers if p.get("Online")]
    facts.append(f"Subnet routers on tailnet: {len(routers)} ({len(online_routers)} online)")

    if not routers:
        return CoderReachabilityDiagnosis(
            code="no_subnet_routes_advertised",
            cause="No peer on your tailnet advertises subnet routes.",
            next_step=(
                f"Either you are not on the '{EXPECTED_TAILNET}' tailnet (check "
                "the name above), or your account is outside `group:employees` "
                f"in the Tailscale policy. See {_TAILSCALE_RUNBOOK_URL} for both, "
                "then reach out to Team DevEx with the facts below."
            ),
            facts=facts,
        )

    if not online_routers:
        names = ", ".join(str(p.get("HostName") or "?") for p in routers)
        return CoderReachabilityDiagnosis(
            code="subnet_router_offline",
            cause=f"Subnet router peer is offline ({names}).",
            next_step=(
                "Wait a minute and retry. If it stays offline, reach out to Team DevEx — the relay likely needs a bounce."
            ),
            facts=facts,
        )

    return CoderReachabilityDiagnosis(
        code="tcp_blocked",
        cause="TCP is blocked despite an online subnet router on your tailnet.",
        next_step=(
            "A non-Tailscale VPN or a local firewall is likely intercepting, "
            "or your account is outside `group:employees` in the Tailscale "
            f"policy. Disable other VPNs and see {_TAILSCALE_RUNBOOK_URL}, or "
            "reach out to Team DevEx."
        ),
        facts=facts,
    )


def ensure_coder_reachable(setup_hint: str = RUNTIME_SETUP_HINT) -> None:
    """Fail fast with a structured diagnosis when the Coder ALB is unreachable.

    Tailscale reporting ``BackendState=Running`` with ``--accept-routes`` does
    not prove the subnet route to the Coder ALB is plumbed — DNS can resolve
    and packets still blackhole. Probe the API directly, and on failure pick
    the single most-likely cause + next step instead of dumping a list of
    commands the engineer has to interpret themselves.

    The Tailscale checks run only when the probe gets no response. A host
    inside the Coder network, such as a devbox, reaches the API without
    Tailscale, and accepting a subnet route that covers its own network sends
    local traffic through the tailnet and disconnects its workspace agent. An
    error response proves the network path works, so Tailscale is not the cause.
    """
    resp = _probe_coder()
    if resp is None:
        ensure_tailscale_connected(setup_hint)
        if ensure_tailscale_routes_accepted():
            resp = _probe_coder()
    if resp is not None and resp.ok:
        return

    diagnosis = _diagnose_unreachable_coder()
    body = "\n".join(
        [
            f"Cannot reach {get_coder_url()} over the tailnet.",
            "",
            f"Cause:     {diagnosis.cause}",
            f"Next step: {diagnosis.next_step}",
            "",
            "Diagnostic facts (safe to share with Team DevEx):",
            *(f"  - {fact}" for fact in diagnosis.facts),
        ]
    )
    _fail(body, cause=diagnosis.code)


def _encode_ssh_option(value: str) -> str:
    """Encode one value for ``coder config-ssh --ssh-option``.

    The flag is a cobra ``StringSlice``, which runs each value through Go's
    ``encoding/csv``. Bare ``"`` in a non-quoted field crashes the parser
    (``parse error: bare " in non-quoted-field``), so SSH options containing
    quotes -- like ``IdentityAgent "/path with spaces"`` -- need to arrive
    CSV-encoded. ``csv.QUOTE_MINIMAL`` only wraps fields that actually need
    it, so plain options like ``ForwardAgent yes`` pass through unchanged.

    coder CSV-decodes the value before writing ``~/.ssh/config``, so the
    file ends up with the literal SSH form we constructed here.
    """
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_MINIMAL).writerow([value])
    return buf.getvalue().rstrip("\r\n")


def _config_ssh_args(*, identity_agent_socket: str | None = None) -> list[str]:
    """Build the base args for ``coder config-ssh``, pinning the managed binary path.

    Appends SSH options that wire up commit signing via SSH agent forwarding:
    ``ForwardAgent yes`` so the laptop's SSH agent reaches the remote, and (on
    macOS) ``IdentityAgent <socket>`` pointed at whichever signing-key agent
    the engineer picked in ``--configure-git-signing`` (Secretive or 1Password).
    ``IdentityAgent`` is omitted when no socket has been chosen yet, leaving
    SSH to fall back to the user's default ``$SSH_AUTH_SOCK``.

    The socket path needs to land double-quoted in ``~/.ssh/config`` because
    1Password's macOS agent lives under ``~/Library/Group Containers/...`` --
    an unquoted space makes ``ssh`` reject the config with "extra arguments
    at end of line." See ``_encode_ssh_option`` for how that survives coder's
    CSV-parsing flag layer.
    """
    args = ["coder", "config-ssh"]
    managed = _MANAGED_CODER_DIR / "coder"
    if managed.is_file():
        args += ["--coder-binary-path", str(managed)]
    args += ["--ssh-option", _encode_ssh_option("ForwardAgent yes")]
    if identity_agent_socket:
        args += ["--ssh-option", _encode_ssh_option(f'IdentityAgent "{identity_agent_socket}"')]
    return args


def _ssh_config_needs_update(*, identity_agent_socket: str | None = None) -> bool:
    """Check whether ``coder config-ssh`` would make changes."""
    result = _run(
        [*_config_ssh_args(identity_agent_socket=identity_agent_socket), "--dry-run", "--yes"],
        capture_output=True,
    )
    if result.returncode != 0:
        return True
    combined = result.stdout + result.stderr
    return "No changes to make" not in combined


def coder_installed() -> bool:
    """Return whether the Coder CLI is available (managed or on PATH)."""
    return (_MANAGED_CODER_DIR / "coder").is_file() or shutil.which("coder") is not None


def get_installed_coder_version() -> str | None:
    """Return the installed Coder CLI version, or None if undetermined."""
    result = _run(["coder", "version", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        version = data.get("version", "")
        if not version:
            return None
        return _normalize_version(version)
    except (json.JSONDecodeError, AttributeError):
        return None


def _warn_version_mismatch() -> None:
    """Warn if the installed Coder CLI doesn't match the expected version."""
    try:
        expected = get_server_version()
    except RuntimeError:
        return

    installed = get_installed_coder_version()
    if installed is None or installed == expected:
        return

    coder_url = get_coder_url()
    click.echo(
        click.style(
            f"Coder CLI v{installed} does not match server v{expected}.\n"
            f"  Run `hogli devbox:setup` or: curl -fsSL {coder_url}/install.sh | sh",
            fg="yellow",
        )
    )


def _install_coder_cli(*, verbose: bool = False) -> None:
    """Install the Coder CLI into ~/.hogli/bin from the deployment's install script."""
    coder_url = get_coder_url()
    try:
        version = get_server_version()
        click.echo(f"Installing coder CLI v{version}...")
    except RuntimeError:
        version = None
        click.echo("Installing coder CLI...")

    prefix = _MANAGED_CODER_DIR.parent
    prefix.mkdir(parents=True, exist_ok=True)
    install_url = shlex.quote(f"{coder_url}/install.sh")
    # `set -o pipefail` so a curl failure fails the pipeline; otherwise `sh`
    # exits 0 with empty stdin and we silently "install" nothing. Invoke via
    # `bash` because `/bin/sh` is `dash` on Debian/Ubuntu and rejects `-o pipefail`.
    cmd = f"set -o pipefail; curl -fsSL {install_url} | sh -s -- --prefix {shlex.quote(str(prefix))}"
    result = subprocess.run(["bash", "-c", cmd], text=True, capture_output=not verbose)
    if result.returncode != 0:
        if not verbose:
            click.echo(result.stdout or "")
            click.echo(result.stderr or "", err=True)
        _fail(f"Coder CLI installation failed.\nTry manually: {cmd}")

    if not verbose:
        # Show only the preamble lines (before shell trace output starts)
        for line in (result.stdout or "").splitlines():
            if line.startswith("+ "):
                break
            stripped = line.strip()
            if stripped:
                click.echo(f"  {stripped}")

    managed = _MANAGED_CODER_DIR / "coder"
    if not managed.is_file():
        _fail(f"Coder CLI install reported success but {managed} is missing.\nTry manually: {cmd}")


def ensure_coder_installed(*, verbose: bool = False) -> None:
    """Install the Coder CLI at the expected version, or reinstall on mismatch."""
    if not coder_installed():
        _install_coder_cli(verbose=verbose)
        return

    try:
        expected = get_server_version()
    except RuntimeError:
        click.echo("coder CLI is installed.")
        return

    installed = get_installed_coder_version()
    if installed is not None and installed != expected:
        click.echo(f"coder CLI v{installed} does not match server v{expected}.")
        _install_coder_cli(verbose=verbose)
    else:
        click.echo("coder CLI is installed.")


def _coder_whoami() -> subprocess.CompletedProcess[str]:
    """Run `coder whoami` against the configured deployment."""
    return _run(["coder", "whoami", "--output", "json"], capture_output=True)


def _coder_user_show_me() -> subprocess.CompletedProcess[str]:
    """Run `coder users show me` against the configured deployment."""
    return _run(["coder", "users", "show", "me", "--output", "json"], capture_output=True)


def coder_authenticated() -> bool:
    """Return whether the local machine is authenticated with Coder."""
    if not coder_installed():
        return False

    return _coder_whoami().returncode == 0


def ensure_coder_authenticated() -> None:
    """Run interactive login when needed."""
    if coder_authenticated():
        click.echo("Coder login is ready.")
        return

    if not coder_installed():
        _fail(f"`coder` is not installed. {RUNTIME_SETUP_HINT}", cause="coder_not_installed")

    coder_url = get_coder_url()
    click.echo(f"Logging in to {coder_url}...")
    result = _run(["coder", "login", coder_url])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ensure_runtime_ready() -> None:
    """Verify runtime prerequisites, failing with the setup hint instead of installing or logging in."""
    ensure_coder_reachable()

    if not coder_installed():
        _fail(f"`coder` is not installed. {RUNTIME_SETUP_HINT}", cause="coder_not_installed")

    if not coder_authenticated():
        _fail(f"Coder login is not ready for {get_coder_url()}. {RUNTIME_SETUP_HINT}", cause="coder_login_not_ready")

    _warn_version_mismatch()


def maybe_configure_ssh(
    *, configure_ssh: bool | None, identity_agent_socket: str | None = None, verbose: bool = False
) -> None:
    """Install Coder SSH config, skipping only when explicitly opted out."""
    if not _ssh_config_needs_update(identity_agent_socket=identity_agent_socket):
        click.echo("Coder SSH config is up to date.")
        return

    if configure_ssh is False:
        click.echo("Skipping SSH config.")
        click.echo("Run `hogli devbox:setup` later if you want local SSH host entries.")
        return

    click.echo("Adding Coder workspace entries to ~/.ssh/config...")
    result = _run(
        [*_config_ssh_args(identity_agent_socket=identity_agent_socket), "--yes"],
        capture_output=not verbose,
    )
    if result.returncode != 0:
        if not verbose:
            click.echo(result.stdout or "")
            click.echo(result.stderr or "", err=True)
        raise SystemExit(result.returncode)

    if not verbose:
        # Show only the "Updated ..." line from coder's output
        for line in (result.stdout or "").splitlines():
            if "Updated" in line:
                click.echo(f"  {line.strip()}")
                break


def print_setup_summary() -> None:
    """Print a short summary after setup completes."""
    click.echo()
    click.echo("Setup complete. Run `hogli devbox:start` to create or start your devbox.")
    click.echo()
    click.echo("Reconfigure one setting:  hogli devbox:setup --configure-<option>")
    click.echo("Show saved configuration: hogli devbox:config:show")
    click.echo("Clear saved settings:     hogli devbox:config:rm --help")
    click.echo()
    click.echo("Other workspace secrets (GH_TOKEN, AWS creds, etc):")
    click.echo("  hogli devbox:secret:list / hogli devbox:secret:set NAME / hogli devbox:secret:rm NAME")


def _first_non_empty_string(*values: Any) -> str | None:
    """Return the first non-empty string value."""
    for value in values:
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value:
                return stripped_value
    return None


def _parse_coder_user_info(payload: str) -> CoderUserInfo:
    """Parse JSON user payloads returned by the Coder CLI."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return CoderUserInfo()

    if isinstance(data, list):
        if not data:
            return CoderUserInfo()
        data = data[0]

    if not isinstance(data, dict):
        return CoderUserInfo()

    username = _first_non_empty_string(data.get("username"), data.get("name"))
    full_name = _first_non_empty_string(data.get("full_name"), data.get("fullName"), data.get("name"))
    email = _first_non_empty_string(data.get("email"))

    user_info = CoderUserInfo()
    if username:
        user_info["username"] = username
    if full_name:
        user_info["full_name"] = full_name
    if email:
        user_info["email"] = email
    return user_info


def get_coder_user_info() -> CoderUserInfo:
    """Return normalized user info for the authenticated Coder user when available."""
    for command in (_coder_user_show_me, _coder_whoami):
        result = command()
        if result.returncode != 0:
            continue

        user_info = _parse_coder_user_info(result.stdout)
        if user_info:
            return user_info

    result = _run(["coder", "whoami"], capture_output=True)
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith("http"):
                username = stripped_line.split()[0].split("@")[0].lower()
                if username:
                    return CoderUserInfo(username=username)

    return CoderUserInfo()


def get_default_git_identity() -> tuple[str | None, str | None]:
    """Return the default Git identity derived from the authenticated Coder profile."""
    user_info = get_coder_user_info()
    git_name = _first_non_empty_string(user_info.get("full_name"), user_info.get("username"))
    git_email = _first_non_empty_string(user_info.get("email"))
    return git_name, git_email


@functools.cache
def get_username() -> str:
    """Get current Coder username (cached -- it cannot change within one invocation).

    Every helper that builds or parses workspace names calls this, and each
    uncached call is a `coder` subprocess. Failures raise instead of caching,
    so an auth retry within the same process still re-probes.
    """
    user_info = get_coder_user_info()
    username = _first_non_empty_string(user_info.get("username"))
    if username:
        return username.lower()

    _fail(
        "Could not determine your Coder username from `coder whoami`.\n"
        f"  Your login may have expired. {RUNTIME_SETUP_HINT}"
    )


def _validate_label(label: str) -> None:
    """Reject labels that don't match the format or collide with a region suffix.

    Region suffixes encode the workspace's region at the end of the name
    (`devbox-rauln-eu`), so a label like `eu` or `foo-eu` would be
    indistinguishable from a region-suffixed workspace once written to disk.
    Rejecting at construction time is cheaper than parsing ambiguity later.
    """
    if not _LABEL_RE.match(label):
        _fail(f"Invalid workspace label '{label}'. Use lowercase alphanumeric and hyphens.")
    for reserved in _RESERVED_LABEL_SUFFIXES:
        if label == reserved or label.endswith(f"-{reserved}"):
            _fail(f"Label '{label}' conflicts with the '-{reserved}' region suffix. Pick a different label.")


def get_workspace_name(label: str | None = None, *, region: str = DEFAULT_REGION) -> str:
    """Derive workspace name from Coder username, optional label, and region.

    The default region is suffix-free for backward compatibility:
    ``devbox-{username}`` (default) or ``devbox-{username}-{label}`` (labeled).
    Non-default regions append a region suffix at the end: ``devbox-{username}-eu``
    or ``devbox-{username}-{label}-eu``.
    """
    base = f"{_WORKSPACE_PREFIX}-{get_username()}"
    suffix = REGION_NAME_SUFFIXES.get(region, "")
    if label is None:
        return f"{base}-{suffix}" if suffix else base
    _validate_label(label)
    return f"{base}-{label}-{suffix}" if suffix else f"{base}-{label}"


def get_default_workspace_prefix() -> str:
    """Return the ``devbox-{username}`` prefix used to identify this user's workspaces."""
    return f"{_WORKSPACE_PREFIX}-{get_username()}"


def _list_workspaces(*, timeout: float | None = None) -> list[dict[str, Any]]:
    """Return raw workspace payloads from the Coder CLI."""
    return _fetch_workspaces(timeout=timeout) or []


def _fetch_workspaces(*, timeout: float | None = None) -> list[dict[str, Any]] | None:
    try:
        result = _run(["coder", "list", "--output", "json"], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None

    try:
        workspaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    return workspaces if isinstance(workspaces, list) else None


def extract_workspace_label(workspace_name: str) -> str | None:
    """Extract the label portion of a full workspace name, stripping any region suffix.

    Returns ``None`` for the default workspace in any region (``devbox-{user}``
    or ``devbox-{user}-eu``). A trailing region suffix is stripped before the
    label is read so ``devbox-{user}-api-eu`` -> ``api`` and ``devbox-{user}-eu``
    -> ``None``. Labels that collide with a region suffix are rejected at
    construction time (see ``_validate_label``), so parsing is unambiguous.
    """
    prefix = get_default_workspace_prefix()
    if workspace_name == prefix:
        return None
    if not workspace_name.startswith(f"{prefix}-"):
        return None
    rest = workspace_name[len(prefix) + 1 :]
    for reserved in _RESERVED_LABEL_SUFFIXES:
        if rest == reserved:
            return None
        if rest.endswith(f"-{reserved}"):
            rest = rest[: -len(reserved) - 1]
            break
    return rest or None


def region_from_workspace_name(workspace_name: str) -> str:
    """Return the region a workspace name encodes via its suffix.

    The name is authoritative -- non-default regions carry a `-{suffix}` and
    the suffix-free form is the default region (see ``REGION_NAME_SUFFIXES``).
    Unlike ``get_workspace_region`` this needs no live ``coder`` metadata, so it
    is correct even for boxes created before the region metadata item existed.
    """
    for region, suffix in REGION_NAME_SUFFIXES.items():
        if suffix and workspace_name.endswith(f"-{suffix}"):
            return region
    return DEFAULT_REGION


def list_user_workspaces() -> list[dict[str, Any]]:
    """Return all workspaces belonging to the current user with the devbox prefix."""
    return fetch_user_workspaces() or []


def fetch_user_workspaces() -> list[dict[str, Any]] | None:
    """Like ``list_user_workspaces``, but ``None`` when Coder could not list workspaces."""
    workspaces = _fetch_workspaces()
    if workspaces is None:
        return None
    prefix = get_default_workspace_prefix()
    return [ws for ws in workspaces if ws.get("name") == prefix or ws.get("name", "").startswith(f"{prefix}-")]


def get_workspace(name: str, workspaces: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Get workspace info by name, or None if it does not exist."""
    for workspace in workspaces if workspaces is not None else _list_workspaces():
        if workspace.get("name") == name:
            return workspace

    return None


def get_workspace_status(workspace: dict[str, Any]) -> str:
    """Extract status string from a workspace payload."""
    return workspace.get("latest_build", {}).get("status", "unknown")


def _workspace_metadata_value(workspace: dict[str, Any], key: str) -> str | None:
    """Return a ``coder_metadata`` item value the template publishes back.

    Items surface under ``latest_build.resources[].metadata[]`` in the ``coder
    list`` payload. Returns ``None`` when the key is absent (e.g. boxes created
    before that item existed) so callers can decide on a fallback.
    """
    for resource in workspace.get("latest_build", {}).get("resources", []):
        for item in resource.get("metadata", []):
            if isinstance(item, dict) and item.get("key") == key:
                value = item.get("value")
                if isinstance(value, str) and value:
                    return value
    return None


def get_workspace_region(workspace: dict[str, Any]) -> str | None:
    """Return the region a workspace lives in, or ``None`` when unknown.

    The template publishes the region as a ``coder_metadata`` item (key
    ``region``). Returns ``None`` for boxes created before the metadata item
    existed so callers can render their own placeholder.
    """
    return _workspace_metadata_value(workspace, REGION_METADATA_KEY)


def get_workspace_disk_size(workspace: dict[str, Any]) -> int | None:
    """Return a workspace's root disk size in GiB, or ``None`` when unknown.

    The template publishes it as a ``coder_metadata`` item (key ``disk``, value
    like ``"100 GiB"``). A clone must request at least the source's size or the
    instance fails to launch from the captured AMI (``InvalidBlockDeviceMapping``).
    """
    value = _workspace_metadata_value(workspace, DISK_METADATA_KEY)
    match = re.search(r"^(\d+)\s*GiB$", value.strip()) if value else None
    return int(match.group(1)) if match else None


def _list_template_presets(template: str) -> list[str]:
    """Return preset names defined on the active version of ``template``, or [] on failure.

    Emits a warning when the coder CLI itself fails (auth/network/version issues) so
    a silent fall-through to ``--preset none`` is distinguishable from a template that
    simply defines no presets.
    """
    result = _run(
        ["coder", "templates", "presets", "list", template, "-o", "json"],
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else "."
        click.echo(
            click.style(
                f"Warning: failed to list presets for template '{template}'{suffix}",
                fg="yellow",
            ),
        )
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [entry["name"] for entry in payload if isinstance(entry, dict) and isinstance(entry.get("name"), str)]


def resolve_template_preset(template: str, requested: str) -> str:
    """Resolve ``requested`` to a preset the template defines, or ``NO_PRESET``.

    Falls back to ``NO_PRESET`` (with a warning when alternatives exist) so
    ``coder create`` never reaches its interactive picker.
    """
    if requested == NO_PRESET:
        return NO_PRESET
    presets = _list_template_presets(template)
    if requested in presets:
        return requested
    if presets:
        click.echo(
            click.style(
                f"Warning: preset '{requested}' not found for template '{template}'. "
                f"Available: {', '.join(presets)}. Falling back to --preset {NO_PRESET}.",
                fg="yellow",
            ),
        )
    return NO_PRESET


def _start_app_param(start_app: bool | None) -> dict[str, str]:
    """Map the tri-state --start-app flag to a creation parameter dict.

    ``None`` (flag omitted) returns ``{}`` so creation uses the template default.
    ``True``/``False`` are written explicitly so the choice survives even if the
    template default changes.
    """
    if start_app is None:
        return {}
    return {AUTO_START_APP_PARAMETER: "true" if start_app else "false"}


def create_workspace(
    name: str,
    disk_size: int | None,
    git_name: str | None = None,
    git_email: str | None = None,
    dotfiles_uri: str | None = None,
    repo: str = "https://github.com/PostHog/posthog",
    *,
    region: str = DEFAULT_REGION,
    template: str = DEFAULT_TEMPLATE,
    preset: str = DEFAULT_PRESET,
    start_app: bool | None = None,
    verbose: bool = False,
) -> None:
    """Create a new Coder workspace.

    Only parameters with explicit caller-supplied values are forwarded.
    Anything the template defines but we do not supply falls back to the
    template's Terraform default via ``--use-parameter-defaults``. If a
    forwarded parameter does not exist on the chosen template, coder errors
    pre-provisioning and the retry loop drops the offending key.

    ``region`` is forwarded as ``workspace_region``. On a template that does
    not yet declare it, the retry loop drops it and the box lands in the
    template default (us-east-1) -- so shipping this before the template
    update is harmless. On a template that declares it but does not offer the
    requested value yet (eu-central-1 before the EU infra is live), coder
    rejects it as an invalid option, which is *not* the "parameter not
    present" error, so the failure surfaces instead of silently falling back.

    ``preset`` is resolved against the template's actual presets via
    ``resolve_template_preset``; pass ``NO_PRESET`` to opt out.
    """
    parameters: dict[str, str] = {
        "repo": repo,
        WORKSPACE_REGION_PARAMETER: region,
    }
    if disk_size is not None:
        parameters[DISK_SIZE_PARAMETER] = str(disk_size)
    if git_name:
        parameters[GIT_NAME_PARAMETER] = git_name
    if git_email:
        parameters[GIT_EMAIL_PARAMETER] = git_email
    if dotfiles_uri:
        parameters[DOTFILES_URI_PARAMETER] = dotfiles_uri
    parameters.update(_start_app_param(start_app))

    resolved_preset = resolve_template_preset(template, preset)
    base_args = [
        "coder",
        "create",
        name,
        "--template",
        template,
        "--preset",
        resolved_preset,
        "--use-parameter-defaults",
        *AUTOMATIC_UPDATES_ARGS,
        "--yes",
    ]
    result = _run_with_param_retry(base_args, parameters, verbose=verbose)
    if result.returncode != 0:
        _exit_for_failed_build(result.returncode, result.stdout)


# A metadata read over ssh is near-instant; keep the ceiling tight so a wedged
# box fails fast instead of hanging the clone.
INSTANCE_ID_TIMEOUT = 60

_INSTANCE_ID_RE = re.compile(r"\bi-[0-9a-f]{8,17}\b")

# Runs ON the source devbox (over its ssh alias) and prints the box's own EC2
# instance id from IMDSv2. A read-only metadata lookup -- no AWS credentials and
# no imaging permissions. The clone template captures the AMI from this id
# server-side, after verifying the instance carries the requester's owner tag.
_INSTANCE_ID_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
TOKEN=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
curl -sS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id
"""


def get_source_instance_id(workspace_name: str, *, timeout: int = INSTANCE_ID_TIMEOUT) -> str:
    """Return the source devbox's own EC2 instance id (``i-...``), read from IMDS.

    A read-only metadata lookup over the box's ssh alias -- hogli makes no AWS
    calls and needs no imaging permissions. The clone template captures the AMI
    from this id server-side, after verifying the instance carries the
    requester's ownership tag.
    """
    if not coder_ssh_alias_configured(workspace_name):
        _fail(f"ssh alias for '{workspace_name}' is not configured. {RUNTIME_SETUP_HINT}")

    encoded = base64.b64encode(_INSTANCE_ID_SCRIPT.encode()).decode()
    try:
        result = subprocess.run(
            ["ssh", _ssh_host_alias(workspace_name), f"echo {encoded} | base64 -d | bash"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _fail(f"Timed out after {timeout}s reading the source devbox's instance id.")

    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        _fail("Failed to read the source devbox's instance id over ssh.")

    match = _INSTANCE_ID_RE.search(result.stdout)
    if match is None:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        _fail("Could not determine the source devbox's EC2 instance id.")
    return match.group(0)


def clone_workspace(
    target: str,
    *,
    source_instance_id: str,
    disk_size: int,
    region: str,
    template: str = DEFAULT_TEMPLATE,
    verbose: bool = False,
) -> None:
    """Create ``target`` as a clone via server-side AMI capture.

    ``clone_source_instance_id`` tells the template which instance to image; the
    template verifies ownership and captures the AMI itself, so hogli passes
    only the id. ``disk_size`` must be at least the source's or the clone fails
    to launch from the captured snapshot; ``region`` must match the source's
    (the AMI is region-scoped). Every other parameter falls back to the
    template default (``--use-parameter-defaults``), which resolves git identity
    to the workspace owner -- the source's on-disk config rides in via the AMI.

    ``--copy-parameters-from`` is deliberately NOT used: Coder resolves a copied
    value ahead of an explicit ``--parameter``, so it silently overrides
    ``clone_source_instance_id`` back to the source's empty value and boots a
    blank golden box as a successful clone. This also skips the param-retry
    shim, which would drop ``clone_source_instance_id`` on a template that
    predates the clone change; that key is load-bearing, so we fail loudly.
    """
    # --preset none is required: newer Coder shows an interactive preset picker
    # that --yes does not bypass, which would hang the build.
    args = _append_parameter_flags(
        [
            "coder",
            "create",
            target,
            "--template",
            template,
            "--preset",
            NO_PRESET,
            "--use-parameter-defaults",
            *AUTOMATIC_UPDATES_ARGS,
            "--yes",
        ],
        {
            CLONE_SOURCE_PARAMETER: source_instance_id,
            DISK_SIZE_PARAMETER: str(disk_size),
            WORKSPACE_REGION_PARAMETER: region,
        },
    )
    result = _run_build(args, verbose=verbose)
    if result.returncode != 0:
        match = _PARAM_NOT_PRESENT_RE.search(result.stdout or "")
        missing = match.group(1) if match else None
        if missing == CLONE_SOURCE_PARAMETER:
            _fail(
                f"This Coder template does not accept '{CLONE_SOURCE_PARAMETER}', so it cannot be "
                "cloned. Deploy the cloud-infra devbox-clone template change first."
            )
        if missing is not None:
            _fail(f"This Coder template does not accept the '{missing}' parameter.")
        raise SystemExit(result.returncode)


def start_workspace(name: str, *, verbose: bool = False) -> None:
    """Start a stopped workspace."""
    result = _run_build(["coder", "start", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        _exit_for_failed_build(result.returncode, result.stdout)


# Must exceed the longest blocking startup script timeout in the posthog-linux
# template, so that Coder reports `start_timeout` itself before this gives up.
AGENT_READY_TIMEOUT = 960
AGENT_READY_POLL_INTERVAL = 3
_AGENT_START_FAILED_STATES = frozenset({"start_error", "start_timeout"})
_AGENT_SHUTDOWN_STATES = frozenset({"shutting_down", "shutdown_error", "shutdown_timeout", "off"})
# A build that is not starting or running lists no agents, so its agent states
# alone never end the wait.
_BUILD_STOPPED_STATUSES = frozenset({"stopping", "stopped", "canceling", "canceled", "deleting", "deleted"})


def _agents(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        agent
        for resource in workspace.get("latest_build", {}).get("resources", [])
        for agent in resource.get("agents") or []
    ]


def wait_for_agent_ready(name: str, *, timeout: int = AGENT_READY_TIMEOUT) -> str:
    """Block until the workspace's startup scripts finish, so "started" means usable.

    Returns the state that ended the wait: ``ready``, a Coder lifecycle state
    (``start_error``, ``start_timeout``), ``build_failed``, ``stopped`` when the
    box shut down, ``agent_timeout`` when the agent never connected,
    ``unavailable`` when `coder list` did not return the box, or ``wait_timeout``.
    """
    deadline = time.monotonic() + timeout
    while True:
        workspace = get_workspace(name, _list_workspaces(timeout=deadline - time.monotonic()))
        if workspace is None:
            return "wait_timeout" if time.monotonic() >= deadline else "unavailable"
        build_status = get_workspace_status(workspace)
        if build_status == "failed":
            return "build_failed"
        if build_status in _BUILD_STOPPED_STATUSES:
            return "stopped"
        agents = _agents(workspace)
        states = {str(agent.get("lifecycle_state", "")) for agent in agents}
        if states == {"ready"}:
            return "ready"
        if failed := sorted(states & _AGENT_START_FAILED_STATES):
            return failed[0]
        if states & _AGENT_SHUTDOWN_STATES:
            return "stopped"
        if any(agent.get("status") == "timeout" for agent in agents):
            return "agent_timeout"
        if time.monotonic() >= deadline:
            return "wait_timeout"
        time.sleep(AGENT_READY_POLL_INTERVAL)


def stop_workspace(name: str, *, verbose: bool = False) -> None:
    """Stop a running workspace."""
    result = _run_build(["coder", "stop", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def restart_workspace(name: str, *, verbose: bool = False) -> None:
    """Restart a running workspace.

    With automatic updates on, a restart of an outdated workspace is a template
    update, and Coder prompts for any new parameter. ``_run_build`` captures the
    output, so the prompt would hang unseen; ``--use-parameter-defaults`` takes
    the template default instead.
    """
    result = _run_build(["coder", "restart", name, "--use-parameter-defaults", "--yes"], verbose=verbose)
    if result.returncode != 0:
        _exit_for_failed_build(result.returncode, result.stdout)


def update_workspace(name: str, *, verbose: bool = False) -> None:
    """Update a workspace to the latest template version and start it.

    ``--use-parameter-defaults`` fills any parameter the new template version
    adds with its default instead of prompting behind the spinner.
    """
    result = _run_build(["coder", "update", name, "--use-parameter-defaults"], verbose=verbose)
    if result.returncode != 0:
        _exit_for_failed_build(result.returncode, result.stdout)
    # `coder update` only streams the build logs, so it exits 0 when the build fails.
    workspace = get_workspace(name)
    if workspace is not None and get_workspace_status(workspace) == "failed":
        if not verbose:
            click.echo(click.style("Build failed. Full output:", fg="red"))
            click.echo(result.stdout, nl=False)
        _exit_for_failed_build(1, result.stdout)


# Mutable template parameter. A change to it changes the type of the same EC2
# instance, so the box keeps its disk.
INSTANCE_TYPE_PARAMETER = "instance_type"
BUILD_WAIT_TIMEOUT = 3600
BUILD_POLL_INTERVAL = 3
_BUILD_DONE_JOB_STATUSES = frozenset({"succeeded", "failed", "canceled"})


@dataclass(frozen=True, kw_only=True, slots=True)
class _FinishedBuild:
    job_status: str
    log_output: str


class _CoderApi:
    """The Coder REST API, called as the user and on the deployment the Coder CLI is logged into.

    The Coder CLI cannot change a mutable parameter on an existing workspace,
    because it resolves the value to the last build's after any ``--parameter``
    flag (cli/parameterresolver.go). The build API takes a provided value
    first, as the Coder dashboard does.
    """

    def __init__(self) -> None:
        whoami = _run(["coder", "whoami", "-o", "json"], capture_output=True)
        if whoami.returncode != 0:
            _fail(f"Could not read your Coder login. {RUNTIME_SETUP_HINT}", cause="coder_login_unreadable")
        self._base_url = f"{json.loads(whoami.stdout)[0]['url'].rstrip('/')}/api/v2"
        self._headers = {"Coder-Session-Token": self._session_token()}

    @staticmethod
    def _session_token() -> str:
        # The CLI authenticates with CODER_SESSION_TOKEN when it is set, but
        # `coder login token` prints only the stored login (cli/login.go).
        if token := os.environ.get("CODER_SESSION_TOKEN"):
            return token
        stored = _run(["coder", "login", "token"], capture_output=True)
        if stored.returncode != 0:
            _fail(f"Could not read your Coder login. {RUNTIME_SETUP_HINT}", cause="coder_login_unreadable")
        return stored.stdout.strip()

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> Any:
        try:
            response = requests.request(method, f"{self._base_url}{path}", headers=self._headers, json=body, timeout=30)
        except requests.RequestException as error:
            _fail(f"Could not reach Coder: {error}", cause="coder_api_unreachable")
        if not response.ok:
            _fail(f"Coder rejected {method} {path}: {response.text}", cause="coder_api_rejected")
        return response.json()

    def poll(self, path: str) -> Any | None:
        """GET ``path``, returning None on a network error or a 5xx so the caller polls again."""
        try:
            response = requests.request("GET", f"{self._base_url}{path}", headers=self._headers, json=None, timeout=30)
        except requests.RequestException:
            return None
        if response.status_code >= 500:
            return None
        if not response.ok:
            _fail(f"Coder rejected GET {path}: {response.text}", cause="coder_api_rejected")
        return response.json()

    def instance_type(self, build_id: str) -> str | None:
        parameters = self.request("GET", f"/workspacebuilds/{build_id}/parameters")
        return next((p["value"] for p in parameters if p["name"] == INSTANCE_TYPE_PARAMETER), None)

    def instance_type_options(self, template_version_id: str) -> list[str]:
        parameters = self.request("GET", f"/templateversions/{template_version_id}/rich-parameters")
        return next(
            ([o["value"] for o in p["options"]] for p in parameters if p["name"] == INSTANCE_TYPE_PARAMETER), []
        )

    def start_on_instance_type(self, workspace_id: str, instance_type: str) -> _FinishedBuild:
        """Start the workspace on ``instance_type`` and wait for the build to finish."""
        build = self.request(
            "POST",
            f"/workspaces/{workspace_id}/builds",
            body={
                "transition": "start",
                "rich_parameter_values": [{"name": INSTANCE_TYPE_PARAMETER, "value": instance_type}],
            },
        )
        deadline = time.monotonic() + BUILD_WAIT_TIMEOUT
        while (status := build["job"]["status"]) not in _BUILD_DONE_JOB_STATUSES:
            if time.monotonic() >= deadline:
                _fail(f"The devbox build did not finish within {BUILD_WAIT_TIMEOUT}s.", cause="build_wait_timeout")
            time.sleep(BUILD_POLL_INTERVAL)
            build = self.poll(f"/workspacebuilds/{build['id']}") or build
        if status == "succeeded":
            return _FinishedBuild(job_status=status, log_output="")
        logs = self.request("GET", f"/workspacebuilds/{build['id']}/logs")
        # A job that fails outside Terraform, such as a lost provisioner, has its cause only in job.error.
        output = "".join(f"{log['output']}\n" for log in logs) + (build["job"].get("error") or "")
        return _FinishedBuild(job_status=status, log_output=output)


def run_with_capacity_fallback(name: str, build: Callable[[], None]) -> None:
    """Run a start build, and on a capacity shortage start the box on the template's other instance types.

    EC2 capacity runs out per availability zone and instance type, so another
    type in the same zone usually has room. The box stays on the type that
    started, and a later shortage on it moves the box on again.
    """
    try:
        build()
        return
    except CapacityShortage:
        pass

    workspace = get_workspace(name)
    if workspace is None:
        raise SystemExit(1)
    api = _CoderApi()
    failed_build = workspace["latest_build"]
    failed_type = api.instance_type(failed_build["id"])
    options = api.instance_type_options(failed_build["template_version_id"])
    if failed_type is None or not options:
        raise SystemExit(1)

    for instance_type in [option for option in options if option != failed_type]:
        click.echo(
            click.style(
                f"AWS has no {failed_type} capacity in the devbox's availability zone. Starting it on {instance_type}...",
                fg="yellow",
            )
        )
        attempt = api.start_on_instance_type(workspace["id"], instance_type)
        if attempt.job_status == "succeeded":
            return
        if _CAPACITY_ERROR not in attempt.log_output:
            click.echo(click.style("Build failed. Full output:", fg="red"))
            click.echo(attempt.log_output, nl=False)
            raise SystemExit(1)
        failed_type = instance_type
    _fail(
        f"AWS has no capacity in the devbox's availability zone for any of {', '.join(options)}. Try again later.",
        cause="capacity_exhausted",
    )


def delete_workspace(name: str, *, verbose: bool = False) -> None:
    """Delete a workspace."""
    result = _run_build(["coder", "delete", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def upsert_user_secret(
    name: str,
    value: str,
    *,
    env_name: str | None = None,
    description: str | None = None,
) -> None:
    """Idempotently set a per-user Coder secret. Requires server >= 2.33.

    Pipes ``value`` via stdin so it never appears in argv, process listings,
    or shell history. Tries ``coder secret create`` first; falls back to
    ``coder secret update`` when the secret already exists. Raises
    ``SystemExit`` (with stderr surfaced) on failure, so callers do not have
    to branch on a return code. ``env_name`` is the workspace-side
    environment variable the secret will be exported as; ``description`` is
    informational.
    """
    flags: list[str] = []
    if env_name is not None:
        flags += ["--env", env_name]
    if description is not None:
        flags += ["--description", description]

    for verb in ("create", "update"):
        payload = subprocess.run(
            _resolve_coder(["coder", "secret", verb, name, *flags]),
            input=value,
            text=True,
            capture_output=True,
        )
        if payload.returncode == 0:
            return

    click.echo(payload.stderr or payload.stdout, err=True)
    raise SystemExit(payload.returncode)


def user_secret_exists(name: str) -> bool:
    """Return whether the current user has a secret with the given name set."""
    result = _run(["coder", "secret", "list", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return False
    try:
        secrets = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(secrets, list):
        return False
    return any(isinstance(s, dict) and s.get("name") == name for s in secrets)


def _ssh_host_alias(name: str) -> str:
    """Return the ``Host`` alias written by ``coder config-ssh`` for the given workspace."""
    return f"coder.{name}"


def ssh_replace(name: str) -> None:
    """SSH via the ``coder.*`` host alias so ``~/.ssh/config`` applies.

    Calling ``coder ssh`` directly bypasses the user's ssh config, breaking
    ``IdentityAgent`` forwarding (Secretive, 1Password) used for commit signing.
    The wildcard ``Host coder.*`` block written by ``coder config-ssh`` keeps
    the Coder tunnel via its ``ProxyCommand``.
    """
    _execvp("ssh", ["ssh", _ssh_host_alias(name)])


def exec_replace(name: str, command: list[str]) -> None:
    """Run a single command in the workspace over the ssh host alias, replacing the process.

    Goes through ``ssh coder.<name>`` rather than ``coder ssh <name> -- cmd``
    for two reasons:

    1. ``coder ssh`` does not propagate the remote command's exit code -- it
       prints ``Process exited with status N`` to stderr but exits 0 itself,
       so callers and agents can't tell success from failure. Real ssh
       forwards the exit code faithfully.
    2. The ``Host coder.*`` block applies the user's ssh config (IdentityAgent
       forwarding), same as :func:`ssh_replace`.

    ``command`` tokens are shell-quoted into one string so the remote login
    shell preserves argument boundaries -- ssh otherwise space-joins argv,
    which would split a token like ``"uname -sm"`` back into two.
    """
    _execvp("ssh", ["ssh", _ssh_host_alias(name), shlex.join(command)])


def run_in_workspace(name: str, command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run one command in the workspace like :func:`exec_replace`, but capture its result.

    For callers that must act on the remote exit code and output instead of
    handing the terminal over to the command.
    """
    return subprocess.run(
        ["ssh", _ssh_host_alias(name), shlex.join(command)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def coder_ssh_alias_configured(name: str) -> bool:
    """Return whether ssh resolves a Coder ``ProxyCommand`` for the workspace host alias.

    :func:`exec_replace` and :func:`ssh_replace` connect through the
    ``Host coder.*`` block that ``coder config-ssh`` writes during
    ``devbox:setup``. When that block is absent, ``ssh coder.<name>`` fails with
    an opaque ``Could not resolve hostname``; callers check this first so they
    can point at setup instead. The block is a wildcard, so any ``name`` probes
    it. Returns ``False`` if ``ssh`` is missing or errors.
    """
    try:
        result = subprocess.run(["ssh", "-G", _ssh_host_alias(name)], capture_output=True, text=True)
    except OSError:
        return False
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        if line.startswith("proxycommand "):
            value = line[len("proxycommand ") :].strip()
            return bool(value) and value.lower() != "none"
    return False


def port_forward_replace(name: str, local_port: int, remote_port: int) -> None:
    """Port-forward to a workspace and replace the current process."""
    _run_or_exit(["coder", "port-forward", name, f"--tcp={local_port}:{remote_port}"])


def logs_replace(name: str, follow: bool) -> None:
    """Tail workspace logs and replace the current process."""
    args = ["coder", "logs", name]
    if follow:
        args.append("--follow")

    _run_or_exit(args)


def open_in_browser(name: str) -> None:
    """Open the workspace dashboard in the default browser."""
    username = get_username()
    webbrowser.open(f"{get_coder_url()}/@{username}/{name}")


def open_vscode(name: str) -> None:
    """Open the workspace in VS Code Desktop via Coder."""
    _run_or_exit(["coder", "open", "vscode", name])


def open_cursor(name: str) -> None:
    """Open the workspace in Cursor via SSH remote."""
    cursor = shutil.which("cursor")
    if not cursor:
        _fail("`cursor` CLI is not on PATH. Open Cursor and enable Shell Integration from the Command Palette.")
    _execvp(cursor, ["cursor", "--remote", f"ssh-remote+{_ssh_host_alias(name)}", "/home/coder/posthog"])


def open_web_ide(name: str) -> None:
    """Open code-server for the workspace."""
    username = get_username()
    webbrowser.open(f"{get_coder_url()}/@{username}/{name}/apps/code-server")


# ---------------------------------------------------------------------------
# Coder user secrets
# ---------------------------------------------------------------------------

CLAUDE_CODE_OAUTH_ENV = "CLAUDE_CODE_OAUTH_TOKEN"


def list_user_secrets() -> list[dict[str, Any]] | None:
    """Return user secrets via ``coder secret list -o json``.

    Returns ``None`` when the CLI rejects the command (older server / missing
    feature flag) so callers can distinguish "no secrets" from "unsupported".
    """
    result = _run(["coder", "secret", "list", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return None
    try:
        secrets = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return secrets if isinstance(secrets, list) else []


def get_user_secret(name: str) -> dict[str, Any] | None:
    """Return a single secret payload by name, or ``None`` if not present."""
    secrets = list_user_secrets() or []
    for secret in secrets:
        if isinstance(secret, dict) and secret.get("name") == name:
            return secret
    return None


def has_claude_oauth_secret() -> bool:
    """Return whether a Coder user secret named ``CLAUDE_CODE_OAUTH_TOKEN`` exists."""
    return get_user_secret(CLAUDE_CODE_OAUTH_ENV) is not None


def delete_user_secret(name: str) -> subprocess.CompletedProcess[str]:
    """Delete a Coder user secret by name."""
    return _run(["coder", "secret", "delete", name, "--yes"], capture_output=True)


# ---------------------------------------------------------------------------
# Shared workspace helpers
# ---------------------------------------------------------------------------


def resolve_shared_workspace_name(user: str, label: str | None = None) -> str:
    """Build a workspace name for another user's workspace.

    Mirrors the default-region form of :func:`get_workspace_name`:
    ``devbox-{user}`` for the default workspace, ``devbox-{user}-{label}``
    for a labeled one. The caller's own region preference is intentionally
    NOT applied -- the remote workspace's region is determined by its owner,
    not the accessor, so a region suffix here would just guess wrong.
    Callers needing a shared workspace in a non-default region should pass
    the full workspace name via ``--name``.
    """
    base = f"{_WORKSPACE_PREFIX}-{user}"
    if label is None:
        return base
    return f"{base}-{label}"


def parse_workspace_target(target: str, *, region: str = DEFAULT_REGION) -> str:
    """Parse a workspace target string into a full workspace name.

    Supports:
    - ``@user`` -> another user's default workspace
    - ``@user/label`` -> another user's labeled workspace
    - ``label`` -> current user's labeled workspace

    ``region`` controls the region suffix applied to OWN labels only.
    Shared targets (``@user[/label]``) ignore it -- see
    :func:`resolve_shared_workspace_name`.
    """
    if target.startswith("@"):
        rest = target[1:]
        if "/" in rest:
            user, label = rest.split("/", 1)
            if not user or not label:
                raise click.UsageError("Expected @user/label but got an empty user or label.")
            return resolve_shared_workspace_name(user, label)
        if not rest:
            raise click.UsageError("Expected @user but got bare '@'.")
        return resolve_shared_workspace_name(rest)
    return get_workspace_name(target, region=region)


def share_workspace(name: str, users: list[str], role: str = "use") -> None:
    """Grant workspace access to one or more users."""
    user_spec = ",".join(f"{u}:{role}" for u in users)
    result = _run(["coder", "sharing", "share", name, "--user", user_spec])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def unshare_workspace(name: str, users: list[str]) -> None:
    """Revoke workspace access from one or more users."""
    for user in users:
        result = _run(["coder", "sharing", "remove", name, "--user", user])
        if result.returncode != 0:
            raise SystemExit(result.returncode)


def get_sharing_status(name: str) -> subprocess.CompletedProcess[str]:
    """Return the output of ``coder sharing status`` for a workspace."""
    return _run(["coder", "sharing", "status", name], capture_output=True)


def get_shared_users(name: str) -> list[str]:
    """Return usernames that a workspace is shared with (empty if none)."""
    result = get_sharing_status(name)
    if result.returncode != 0:
        return []
    users: list[str] = []
    for line in result.stdout.strip().splitlines()[1:]:  # skip header
        parts = line.split()
        if parts and parts[0] != "-":
            users.append(parts[0])
    return users


def list_shared_workspaces() -> list[dict[str, Any]]:
    """Return workspaces that other users have shared with the current user."""
    result = _run(["coder", "list", "--search", "shared:true owner:!me", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return []

    try:
        workspaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return workspaces if isinstance(workspaces, list) else []


def list_coder_users() -> list[dict[str, Any]]:
    """Return all active users on the Coder deployment."""
    result = _run(["coder", "users", "list", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return []

    try:
        users = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return [u for u in users if isinstance(u, dict) and u.get("status") == "active"]
