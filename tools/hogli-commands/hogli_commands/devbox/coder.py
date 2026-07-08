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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import click
import requests
from hogli.manifest import load_manifest

_MACOS_TAILSCALE_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
_TAILSCALE_RUNBOOK_URL = "https://runbooks.posthog.com/vpn/#tailscale"
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
# forwarded on `coder create` only -- never on `coder update` or the pre-start
# parameter sync. Coder carries an immutable parameter's value forward on its
# own during an update and *rejects* any explicit `--parameter
# workspace_region=` with "parameter is immutable and cannot be updated". The
# option-change re-prompt that no flag can bypass only applies to *mutable*
# parameters, so forwarding the region here breaks every resume instead of
# suppressing a picker. Valid values match the template contract exactly.
WORKSPACE_REGION_PARAMETER = "workspace_region"
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
# start (including coder task runs); the workspace template reads it to populate
# user.signingkey. The matching private key never leaves 1Password. The `GIT_`
# prefix is reserved by Coder, so the workspace-side env name cannot start with
# it.
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


def _fail(message: str) -> NoReturn:
    """Print a short actionable error and exit."""
    click.echo(click.style(message, fg="red"))
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


def _run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with consistent text handling."""
    return subprocess.run(_resolve_coder(args), capture_output=capture_output, text=True)


def _run_or_exit(args: list[str]) -> None:
    """Replace the current process with a Coder command or exit with its status."""
    resolved = _resolve_coder(args)
    coder_path = resolved[0] if resolved else shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, resolved)

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
    unchanged. Used by every write path that forwards parameters (`coder
    create`, `coder update`) so callers never have to know which keys the
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


def tailscale_connected() -> bool:
    """Check if Tailscale is running and connected."""
    status = _tailscale_status()
    return bool(status and status.get("BackendState") == "Running")


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
            f"  Then {setup_hint}"
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
            f"  Then {setup_hint}"
        )

    _fail(
        "Tailscale is installed but not connected.\n"
        f"  {_tailscale_connect_hint()}\n"
        f"  See {_TAILSCALE_RUNBOOK_URL} if you have not yet been added to the tailnet.\n"
        f"  Then {setup_hint}"
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


def ensure_tailscale_routes_accepted() -> None:
    """Enable Tailscale subnet route acceptance when peers advertise routes."""
    if _tailscale_routes_accepted():
        return

    tailscale_path = _resolve_tailscale()
    if not tailscale_path:
        return

    click.echo("Enabling Tailscale subnet routes (required for devbox access)...")
    cmd = [tailscale_path, "set", "--accept-routes"]
    if sys.platform != "darwin" and hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", *cmd]

    result = subprocess.run(cmd, env=_tailscale_env(tailscale_path))
    if result.returncode != 0:
        manual = "tailscale set --accept-routes" if sys.platform == "darwin" else "sudo tailscale set --accept-routes"
        _fail(f"Failed to enable Tailscale subnet routes. Run manually: {manual}")


def coder_reachable(timeout: float = 5.0) -> bool:
    """Return whether the Coder deployment responds on /api/v2/buildinfo."""
    coder_url = get_coder_url()
    try:
        resp = requests.get(f"{coder_url}/api/v2/buildinfo", timeout=timeout)
    except requests.RequestException:
        return False
    return resp.ok


@dataclass(frozen=True)
class CoderReachabilityDiagnosis:
    """Why the Coder deployment is unreachable, with a single actionable next step.

    The structured form lets the caller present one concrete cause and one
    fix rather than a list of commands the user has to interpret. ``facts``
    is a short list of diagnostic data (tailnet name, resolved IP, peer
    health) that is safe to share verbatim when asking for help.
    """

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
        current_tailnet = status.get("CurrentTailnet")
        if isinstance(current_tailnet, dict):
            name = current_tailnet.get("Name")
            if isinstance(name, str) and name:
                tailnet_name = name
                facts.append(f"Tailscale tailnet: {name}")
        if tailnet_name is None:
            facts.append("Tailscale tailnet: <unknown>")
    else:
        facts.append("Tailscale status: unavailable")

    resolved_ip = _resolve_host_ip(host)
    if resolved_ip is None:
        facts.append(f"DNS for {host}: failed")
        return CoderReachabilityDiagnosis(
            cause=f"DNS lookup for {host} failed.",
            next_step=(
                "MagicDNS may be off or you may be on the wrong tailnet. "
                "Verify the tailnet name above is PostHog's, then run "
                "`sudo tailscale up --accept-dns`."
            ),
            facts=facts,
        )
    facts.append(f"DNS for {host}: {resolved_ip}")

    if _tcp_reachable(host, 443):
        facts.append(f"TCP {host}:443: open")
        return CoderReachabilityDiagnosis(
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
            cause="No peer on your tailnet advertises subnet routes.",
            next_step=(
                "Either you are not on the PostHog tailnet (check the name "
                "above), or your account has not been added to the Tailscale "
                f"policy yet. See {_TAILSCALE_RUNBOOK_URL} for the policy "
                "request flow, then reach out to Team DevEx with the facts below."
            ),
            facts=facts,
        )

    if not online_routers:
        names = ", ".join(str(p.get("HostName") or "?") for p in routers)
        return CoderReachabilityDiagnosis(
            cause=f"Subnet router peer is offline ({names}).",
            next_step=(
                "Wait a minute and retry. If it stays offline, reach out to Team DevEx — the relay likely needs a bounce."
            ),
            facts=facts,
        )

    return CoderReachabilityDiagnosis(
        cause="TCP is blocked despite an online subnet router on your tailnet.",
        next_step=(
            "A non-Tailscale VPN or a local firewall is likely intercepting, "
            "or the Tailscale policy does not grant your account devbox "
            f"access. Disable other VPNs and see {_TAILSCALE_RUNBOOK_URL} to "
            "confirm policy membership, or reach out to Team DevEx."
        ),
        facts=facts,
    )


def ensure_coder_reachable() -> None:
    """Fail fast with a structured diagnosis when the Coder ALB is unreachable.

    Tailscale reporting ``BackendState=Running`` with ``--accept-routes`` does
    not prove the subnet route to the Coder ALB is plumbed — DNS can resolve
    and packets still blackhole. Probe the API directly, and on failure pick
    the single most-likely cause + next step instead of dumping a list of
    commands the engineer has to interpret themselves.
    """
    if coder_reachable():
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
    _fail(body)


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
        _fail(f"`coder` is not installed. {RUNTIME_SETUP_HINT}")

    coder_url = get_coder_url()
    click.echo(f"Logging in to {coder_url}...")
    result = _run(["coder", "login", coder_url])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ensure_runtime_ready() -> None:
    """Verify runtime prerequisites without mutating host setup."""
    ensure_tailscale_connected()
    ensure_tailscale_routes_accepted()
    ensure_coder_reachable()

    if not coder_installed():
        _fail(f"`coder` is not installed. {RUNTIME_SETUP_HINT}")

    if not coder_authenticated():
        _fail(f"Coder login is not ready for {get_coder_url()}. {RUNTIME_SETUP_HINT}")

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


def _list_workspaces() -> list[dict[str, Any]]:
    """Return raw workspace payloads from the Coder CLI."""
    result = _run(["coder", "list", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return []

    try:
        workspaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return workspaces if isinstance(workspaces, list) else []


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
    prefix = get_default_workspace_prefix()
    return [ws for ws in _list_workspaces() if ws.get("name") == prefix or ws.get("name", "").startswith(f"{prefix}-")]


def get_workspace(name: str, workspaces: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Get workspace info by name, or None if it does not exist."""
    for workspace in workspaces if workspaces is not None else _list_workspaces():
        if workspace.get("name") == name:
            return workspace

    return None


def get_workspace_status(workspace: dict[str, Any]) -> str:
    """Extract status string from a workspace payload."""
    return workspace.get("latest_build", {}).get("status", "unknown")


def get_workspace_region(workspace: dict[str, Any]) -> str | None:
    """Return the region a workspace lives in, or ``None`` when unknown.

    The template publishes the region as a ``coder_metadata`` item (key
    ``region``), which surfaces under ``latest_build.resources[].metadata[]``
    in the ``coder list`` payload. Returns ``None`` for boxes created before
    the metadata item existed so callers can render their own placeholder.
    """
    resources = workspace.get("latest_build", {}).get("resources", [])
    for resource in resources:
        for item in resource.get("metadata", []):
            if isinstance(item, dict) and item.get("key") == REGION_METADATA_KEY:
                value = item.get("value")
                if isinstance(value, str) and value:
                    return value
    return None


def get_workspace_disk_size(workspace: dict[str, Any]) -> int | None:
    """Return a workspace's root disk size in GiB, or ``None`` when unknown.

    The template publishes it as a ``coder_metadata`` item (key ``disk``, value
    like ``"100 GiB"``) under ``latest_build.resources[].metadata[]``. A clone
    must request at least the source's size or the instance fails to launch from
    the captured AMI (``InvalidBlockDeviceMapping``).
    """
    resources = workspace.get("latest_build", {}).get("resources", [])
    for resource in resources:
        for item in resource.get("metadata", []):
            if isinstance(item, dict) and item.get("key") == DISK_METADATA_KEY:
                match = re.search(r"\d+", str(item.get("value", "")))
                if match:
                    return int(match.group(0))
    return None


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
    """Map the tri-state --start-app flag to a parameter dict (empty = leave as-is).

    ``None`` (flag omitted) returns ``{}`` so the value stays sticky on an
    existing workspace and falls back to the template default on creation.
    ``True``/``False`` are written explicitly so the choice survives even if the
    template default changes.
    """
    if start_app is None:
        return {}
    return {AUTO_START_APP_PARAMETER: "true" if start_app else "false"}


def create_workspace(
    name: str,
    disk_size: int,
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
        "disk_size": str(disk_size),
        "repo": repo,
        WORKSPACE_REGION_PARAMETER: region,
    }
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
        "--yes",
    ]
    result = _run_with_param_retry(base_args, parameters, verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


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
            "--yes",
        ],
        {
            CLONE_SOURCE_PARAMETER: source_instance_id,
            "disk_size": str(disk_size),
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
        raise SystemExit(result.returncode)


def stop_workspace(name: str, *, verbose: bool = False) -> None:
    """Stop a running workspace."""
    result = _run_build(["coder", "stop", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def restart_workspace(name: str, *, verbose: bool = False) -> None:
    """Restart a running workspace."""
    result = _run_build(["coder", "restart", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def update_workspace(
    name: str,
    parameters: dict[str, str] | None = None,
    *,
    verbose: bool = False,
) -> None:
    """Update a workspace to the latest template version.

    ``--use-parameter-defaults`` lets coder fall back to the template's own
    defaults for any parameter not explicitly supplied here, so we never
    need a hogli-side defaults dict. Parameters carried over from a
    previous template (e.g. a saved ``dotfiles_uri`` that the new template
    does not declare) are dropped by the retry shim instead of aborting
    the update.
    """
    base_args = ["coder", "update", name, "--use-parameter-defaults"]
    result = _run_with_param_retry(base_args, parameters or {}, verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def delete_workspace(name: str, *, verbose: bool = False) -> None:
    """Delete a workspace."""
    result = _run_build(["coder", "delete", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def update_workspace_parameters(name: str, parameters: dict[str, str]) -> None:
    """Update mutable workspace parameters.

    Goes through the same retry shim as ``create_workspace`` so a stale
    local config key (for example, a saved ``dotfiles_uri`` after the user
    switches templates) does not abort the pre-start sync.
    """
    base_args = ["coder", "update", name, "--use-parameter-defaults"]
    result = _run_with_param_retry(base_args, parameters)
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
    os.execvp("ssh", ["ssh", _ssh_host_alias(name)])


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
    os.execvp("ssh", ["ssh", _ssh_host_alias(name), shlex.join(command)])


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


def create_task(
    prompt: str | None,
    *,
    task_name: str | None = None,
    quiet: bool = False,
    template: str = DEFAULT_TEMPLATE,
) -> None:
    """Create a Coder task on the given workspace template.

    When ``prompt`` is None, ``--stdin`` is passed so coder reads the prompt
    from the parent process's stdin; otherwise it is forwarded as the
    positional input argument. Execs into the coder CLI so stdin, stdout,
    and the exit code flow through unchanged.
    """
    args = ["coder", "task", "create", "--template", template]
    if task_name:
        args += ["--name", task_name]
    if quiet:
        args.append("--quiet")
    if prompt is None:
        args.append("--stdin")
    else:
        args.append(prompt)
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
    os.execvp(cursor, ["cursor", "--remote", f"ssh-remote+{_ssh_host_alias(name)}", "/home/coder/posthog"])


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
