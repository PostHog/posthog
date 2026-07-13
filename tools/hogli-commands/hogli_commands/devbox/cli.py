"""CLI commands for remote devbox management.

Provides hogli devbox:* commands for managing Coder-based remote dev environments.
"""

from __future__ import annotations

import os
import sys
import errno
import shutil
import socket
import functools
import subprocess
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
from hogli.manifest import get_manifest

from . import mutagen
from .coder import (
    CLAUDE_CODE_OAUTH_ENV,
    DEFAULT_PRESET,
    DEFAULT_REGION,
    DEFAULT_TEMPLATE,
    DOTFILES_URI_PARAMETER,
    GIT_EMAIL_PARAMETER,
    GIT_NAME_PARAMETER,
    GIT_SIGNING_KEY_SECRET,
    REGIONS,
    _diagnose_unreachable_coder,
    _fail,
    _start_app_param,
    clone_workspace,
    coder_authenticated,
    coder_installed,
    coder_reachable,
    coder_ssh_alias_configured,
    create_task,
    create_workspace,
    delete_user_secret,
    delete_workspace,
    ensure_coder_authenticated,
    ensure_coder_installed,
    ensure_coder_reachable,
    ensure_runtime_ready,
    ensure_tailscale_connected,
    ensure_tailscale_routes_accepted,
    exec_replace,
    extract_workspace_label,
    get_coder_url,
    get_coder_user_info,
    get_default_git_identity,
    get_shared_users,
    get_sharing_status,
    get_source_instance_id,
    get_username,
    get_workspace,
    get_workspace_disk_size,
    get_workspace_name,
    get_workspace_region,
    get_workspace_status,
    has_claude_oauth_secret,
    list_coder_users,
    list_shared_workspaces,
    list_user_secrets,
    list_user_workspaces,
    logs_replace,
    maybe_configure_ssh,
    open_cursor,
    open_in_browser,
    open_vscode,
    open_web_ide,
    parse_workspace_target,
    port_forward_replace,
    print_setup_summary,
    region_from_workspace_name,
    restart_workspace,
    server_supports_user_secrets,
    share_workspace,
    ssh_replace,
    start_workspace,
    stop_workspace,
    tailscale_connected,
    unshare_workspace,
    update_workspace,
    update_workspace_parameters,
    upsert_user_secret,
    user_secret_exists,
)
from .config import (
    DevboxConfig,
    clear_dotfiles_uri,
    clear_git_identity,
    clear_region,
    load_config,
    save_dotfiles_uri,
    save_git_identity,
    save_region,
)

_LEGACY_KEYCHAIN_SERVICE = "posthog-claude-oauth-token"
_POSTHOG_COMMIT_SIGNING_HANDBOOK_URL = "https://posthog.com/handbook/engineering/security#commit-signing"

# Reaching a devbox requires a Tailscale ACL grant. Engineers get it from
# group:engineering in the cloud-infra tailnet policy; without it the Coder
# control plane (10.70.0.1:443) is simply unroutable and every devbox command
# fails at the reachability check.
_TAILNET_POLICY_URL = "https://github.com/PostHog/posthog-cloud-infra/blob/main/tailnet-policy.hujson"
_TAILNET_ACCESS_PREREQ = (
    "Devbox access needs your email in `group:engineering` in "
    "posthog-cloud-infra/tailnet-policy.hujson.\n"
    f"    Not granted yet? Add yourself via PR: {_TAILNET_POLICY_URL}"
)

WORKSPACE_STATUS_COLORS = {
    "running": "green",
    "stopped": "yellow",
    "starting": "cyan",
    "stopping": "yellow",
    "failed": "red",
    "deleting": "red",
}
PENDING_WORKSPACE_STATES = {"starting", "stopping", "deleting"}

# Printed whenever --start-app/--no-start-app is passed but cannot be applied:
# the parameter is only pushed on the pre-start sync of a stopped workspace,
# so the flag is dropped (not queued) on running/transitioning boxes.
_START_APP_NOT_APPLIED_NOTE = "Note: --start-app/--no-start-app was not applied; re-run it once the devbox is stopped."


def resolve_workspace_name(
    workspace: str | None, *, region: str | None = None
) -> tuple[str, list[dict[str, Any]] | None]:
    """Resolve a workspace target into a full workspace name.

    Supports:
    - ``None`` -> user's default workspace (auto-selects when only one exists)
    - ``"@user"`` -> another user's default workspace
    - ``"@user/label"`` -> another user's labeled workspace
    - ``"label"`` -> current user's labeled workspace

    Returns (name, workspaces) where workspaces is the already-fetched list
    when available, so callers can skip a second ``_list_workspaces`` call.

    ``region`` controls the region suffix used when constructing names for
    workspaces that don't exist yet (a bare ``devbox:start --region`` bypasses
    this resolver and targets the region's default name directly). When
    resolving an OWN label against the user's actual workspaces, the region
    suffix is treated as a preference, not a constraint: if the preferred
    name doesn't exist but a workspace with the same label exists in another
    region, that one is returned. The same fallback applies to the default
    workspace in the multi-box case. This keeps a saved region pref from
    silently masking existing workspaces created before the pref was set.
    """
    effective_region = region if region is not None else _preferred_region()
    if workspace is not None:
        target_name = parse_workspace_target(workspace, region=effective_region)
        # Shared workspace targets (`@user[/label]`) are looked up against the
        # remote owner, so cross-region label fallback is the owner's
        # responsibility -- skip it here.
        if workspace.startswith("@"):
            return target_name, None
        return _resolve_own_label(target_name)

    workspaces = list_user_workspaces()

    if len(workspaces) == 0:
        return get_workspace_name(region=effective_region), workspaces

    if len(workspaces) == 1:
        return workspaces[0]["name"], workspaces

    # Multiple workspaces -- prefer the effective region's default, then
    # defaults in other regions (a region pref should not mask the box the
    # user actually has -- same philosophy as the label fallback above).
    existing_names = {ws.get("name") for ws in workspaces}
    for candidate_region in (effective_region, *(r for r in REGIONS if r != effective_region)):
        default_name = get_workspace_name(region=candidate_region)
        if default_name in existing_names:
            return default_name, workspaces

    # No default among multiple -- require explicit workspace argument
    labels = [extract_workspace_label(ws["name"]) or "(default)" for ws in workspaces]
    _fail("Multiple workspaces found. Specify which one:\n" + "".join(f"  {lbl}\n" for lbl in labels))
    raise SystemExit(1)  # unreachable; helps ty see the function doesn't fall through


def _resolve_own_label(target_name: str) -> tuple[str, list[dict[str, Any]] | None]:
    """Return ``(name, workspaces)`` for an own-label target, falling back across regions.

    If ``target_name`` matches an existing workspace, return it directly.
    Otherwise look for any of the user's workspaces with the same label and
    return that. When no candidate exists, return ``target_name`` so the
    downstream "not found" path runs with a stable name.
    """
    workspaces = list_user_workspaces()
    if any(ws.get("name") == target_name for ws in workspaces):
        return target_name, workspaces
    label = extract_workspace_label(target_name)
    if label is not None:
        for ws in workspaces:
            if extract_workspace_label(ws.get("name", "")) == label:
                return ws["name"], workspaces
    return target_name, workspaces


def _local_port_is_available(port: int) -> bool:
    """Return whether the given localhost TCP port can be bound."""
    for host in ("127.0.0.1", "::1"):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
        except OSError as err:
            if err.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                continue
            return False
    return True


def workspace_argument(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Shared Click decorator adding an optional ``WORKSPACE`` positional argument.

    Accepts a label for the current user's workspace, or ``@user[/label]``
    for another user's shared workspace.  ``--name`` / ``-n`` is accepted as
    an explicit alternative (e.g. ``--name api`` instead of just ``api``).
    """

    @click.argument("workspace", required=False, default=None)
    @click.option("--name", "-n", "workspace_name", default=None, help="Workspace label or @user[/label] target")
    @functools.wraps(fn)
    def wrapper(*args: Any, workspace: str | None = None, workspace_name: str | None = None, **kwargs: Any) -> Any:
        if workspace and workspace_name:
            raise click.UsageError("Pass WORKSPACE or --name, not both.")
        return fn(*args, workspace=workspace_name or workspace, **kwargs)

    return wrapper


def _print_connection_info(name: str) -> None:
    """Print connection commands after workspace is ready."""
    suffix = _workspace_arg_suffix(name)
    commands = [
        ("SSH", "devbox:ssh"),
        ("Open", "devbox:open"),
        ("VS Code", "devbox:open --vscode"),
        ("Cursor", "devbox:open --cursor"),
        ("Web IDE", "devbox:open --web"),
        ("Forward", "devbox:forward"),
        ("Logs", "devbox:logs -f"),
        ("Status", "devbox:status"),
        ("Stop", "devbox:stop"),
    ]

    click.echo()
    for label, command in commands:
        click.echo(f"  {label:<8} hogli {command}{suffix}")

    if not mutagen.sync_list(label_selector=mutagen.workspace_label_selector(name)):
        click.echo()
        click.echo(f"  Tip: run `hogli devbox:sync{suffix}` to mirror your local checkout to this devbox.")


def _workspace_arg_suffix(name: str) -> str:
    """Return the optional CLI suffix for a named workspace."""
    label = extract_workspace_label(name)
    return f" {label}" if label else ""


def _get_workspace_or_fail(name: str, workspaces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a workspace or exit with a consistent message when missing."""
    workspace = get_workspace(name, workspaces)
    if workspace is not None:
        return workspace
    _fail("No devbox found. Run 'hogli devbox:start' to create one.")
    raise SystemExit(1)  # unreachable; helps ty see the function doesn't fall through


def _workspace_status_color(status: str) -> str:
    """Return the display color for a workspace status."""
    return WORKSPACE_STATUS_COLORS.get(status, "white")


def _ljust_styled(text: str, width: int) -> str:
    """Left-justify a click-styled string to ``width`` *visible* columns.

    A plain ``f"{text:<width}"`` counts the invisible ANSI escape codes toward
    the width and under-pads colored cells; measure off the unstyled text so
    columns line up with their (unstyled) headers.
    """
    return text + " " * max(0, width - len(click.unstyle(text)))


def _render_sync_status(workspace_name: str) -> str:
    """Return a single-line summary of the mutagen sync state for a workspace.

    Reads the first session matching the workspace label. If multiple sessions
    happen to share the label (shouldn't happen via hogli, but possible via
    direct mutagen use), only the first is rendered -- intentionally simple.
    """
    sessions = mutagen.sync_list(label_selector=mutagen.workspace_label_selector(workspace_name))
    if not sessions:
        return click.style("○ not configured", fg="white")
    session = sessions[0]
    if session.get("paused"):
        return click.style("⚠ paused", fg="yellow")
    conflicts = mutagen.conflict_count(session)
    if conflicts:
        return click.style(f"⚠ {conflicts} conflict{'s' if conflicts != 1 else ''}", fg="red")
    status = str(session.get("status", "")).strip() or "running"
    # mutagen reports a stalled sync (box stopped, remote root gone) as a
    # `disconnected`/`halted-*` status; a green dot there would read as healthy.
    if status == "disconnected" or status.startswith("halted"):
        return click.style(f"✗ {status}", fg="red")
    return click.style(f"● {status}", fg="green")


def _sync_workspace_parameters(name: str, extra: dict[str, str] | None = None) -> None:
    """Push local config (git identity, dotfiles) to workspace parameters before start.

    `workspace_region` is intentionally not forwarded: it is immutable, so Coder
    carries it forward on its own and rejects any explicit value on `coder
    update` (see the comment on `WORKSPACE_REGION_PARAMETER`).
    """
    config = load_config()
    params: dict[str, str] = {}

    git_name = config.get("git_name")
    git_email = config.get("git_email")
    if git_name and git_email:
        params[GIT_NAME_PARAMETER] = git_name
        params[GIT_EMAIL_PARAMETER] = git_email

    dotfiles_uri = config.get("dotfiles_uri")
    if dotfiles_uri:
        params[DOTFILES_URI_PARAMETER] = dotfiles_uri

    if extra:
        params.update(extra)

    if params:
        update_workspace_parameters(name, params)


def _start_existing_workspace(
    name: str, workspace: dict[str, Any], *, start_app: bool | None = None, verbose: bool
) -> None:
    """Handle `devbox:start` when the workspace already exists."""
    status = get_workspace_status(workspace)
    if status == "running":
        click.echo(f"Devbox '{name}' is already running.")
        if start_app is not None:
            # Pushing the parameter needs `coder update`, which rebuilds a
            # running workspace -- only safe on the pre-start sync below.
            click.echo(_START_APP_NOT_APPLIED_NOTE)
        _print_connection_info(name)
        return

    if status in PENDING_WORKSPACE_STATES:
        click.echo(f"Devbox '{name}' is in state: {status}")
        click.echo("Wait for the current operation to complete.")
        if start_app is not None:
            click.echo(_START_APP_NOT_APPLIED_NOTE)
        return

    _sync_workspace_parameters(name, extra=_start_app_param(start_app))

    if status == "stopped":
        click.echo(f"Starting devbox '{name}'...")
        start_workspace(name, verbose=verbose)
        click.echo("Started.")
        _print_connection_info(name)
        return

    click.echo(f"Devbox '{name}' is in state: {status}")
    click.echo("Attempting to start...")
    start_workspace(name, verbose=verbose)
    _print_connection_info(name)


def _read_legacy_keychain_token() -> str | None:
    """Read the legacy macOS Keychain Claude token, if present.

    Used during migration only. Older hogli versions stashed the token under
    a generic-password entry; the new flow stores it as a Coder user secret,
    so this read happens once and the entry is then deleted.
    """
    if sys.platform != "darwin":
        return None
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            os.environ.get("USER", "posthog"),
            "-s",
            _LEGACY_KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _delete_legacy_keychain_token() -> bool:
    """Best-effort delete of the legacy macOS Keychain Claude token entry."""
    if sys.platform != "darwin":
        return False
    result = subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-a",
            os.environ.get("USER", "posthog"),
            "-s",
            _LEGACY_KEYCHAIN_SERVICE,
        ],
        capture_output=True,
    )
    return result.returncode == 0


def _prompt_for_claude_token() -> str | None:
    """Prompt for a Claude OAuth token interactively.

    Returns the trimmed token, or ``None`` if the user accepts the empty default.
    """
    click.echo("Run `claude setup-token` in another terminal to generate a token.")
    click.pause("Press Enter when you have the token ready...")
    token = click.prompt(
        "Claude OAuth token (Enter to skip)",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()
    return token or None


def maybe_configure_git_identity(configure_git_identity: bool | None) -> None:
    """Optionally persist Git identity defaults for new workspaces."""
    config = load_config()
    existing_git_name = config.get("git_name")
    existing_git_email = config.get("git_email")

    if configure_git_identity is False:
        if not (existing_git_name and existing_git_email):
            click.echo("Skipping Git identity setup.")
        return

    if configure_git_identity is None and existing_git_name and existing_git_email:
        return

    # Show prompts with best available defaults (saved > coder profile > empty)
    coder_git_name, coder_git_email = get_default_git_identity()
    default_git_name = existing_git_name or coder_git_name or ""
    default_git_email = existing_git_email or coder_git_email or ""

    click.echo()
    click.echo(click.style("Git identity", bold=True))
    click.echo("  Set the name and email used for Git commits inside your workspace.")
    click.echo("  These will be saved and reused for future workspaces.")
    click.echo()

    git_name = click.prompt(
        "Git name",
        default=default_git_name,
        show_default=bool(default_git_name),
    ).strip()
    git_email = click.prompt(
        "Git email",
        default=default_git_email,
        show_default=bool(default_git_email),
    ).strip()
    if not git_name or not git_email:
        _fail("Git name and Git email are both required when configuring workspace Git identity.")

    save_git_identity(git_name, git_email)
    click.echo(f"Saved Git identity for new workspaces: {git_name} <{git_email}>")


def _resolve_local_identity_agent_for_coder() -> str | None:
    """Return the IdentityAgent ssh would use to connect to Coder workspaces, or ``None``.

    Resolves against the deployment hostname so the engineer's existing
    ``Host *`` / ``Host *.posthog.dev`` / specific blocks all flow through.
    """
    coder_host = urllib.parse.urlparse(get_coder_url()).hostname
    if not coder_host:
        return None
    return _resolve_local_identity_agent(coder_host)


def _resolve_local_signing_key() -> str | None:
    """Return the engineer's ``git config user.signingkey``, normalized to a literal SSH public key string.

    Git accepts three formats: a literal ``ssh-... / ecdsa-... / sk-...``
    string, the same with a ``key::`` prefix (used by tools like Secretive),
    or a path to a public-key file. All are normalized here. Returns ``None``
    when the value is unset or the referenced file can't be read.
    """
    result = subprocess.run(
        ["git", "config", "--global", "--get", "user.signingkey"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value:
        return None
    if value.startswith("key::"):
        value = value.removeprefix("key::")
    if value.startswith(("ssh-", "ecdsa-", "sk-")):
        return value
    try:
        return Path(os.path.expanduser(value)).read_text().strip() or None
    except OSError:
        return None


def _resolve_local_identity_agent(host: str) -> str | None:
    """Return the SSH agent socket ``ssh -G <host>`` would use to authenticate, or ``None`` when no specific agent is configured.

    Treats ``none`` (signaling "no agent") and the literal placeholder
    ``SSH_AUTH_SOCK`` (signaling "fall back to the env var") as "no specific
    agent" so callers can decide their own fallback.
    """
    result = subprocess.run(["ssh", "-G", host], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("identityagent "):
            value = line[len("identityagent ") :].strip()
            if value and value.lower() not in ("none", "ssh_auth_sock"):
                return value
            return None
    return None


def maybe_configure_git_signing(
    configure_git_signing: bool | None, *, known_secret_names: set[str] | None = None
) -> None:
    """Propagate the engineer's existing local commit-signing config into devboxes.

    Reads ``git config user.signingkey`` (the public key the engineer already
    signs locally with) and ``ssh -G <coder-host>``'s ``identityagent`` (the
    SSH agent ssh would use for the connection, which is the agent that gets
    forwarded). Pushes the public key to a Coder user secret and pins the
    agent socket as the local IdentityAgent for Coder hosts. No menus, no
    probing -- whatever the engineer has set up locally per the handbook is
    what propagates.
    """
    already_set = (
        GIT_SIGNING_KEY_SECRET in known_secret_names
        if known_secret_names is not None
        else user_secret_exists(GIT_SIGNING_KEY_SECRET)
    )

    if configure_git_signing is False:
        if not already_set:
            click.echo("Skipping Git commit signing setup.")
        return

    if configure_git_signing is None and already_set:
        return

    public_key = _resolve_local_signing_key()
    if not public_key:
        click.echo()
        click.echo(click.style("Git commit signing (skipped)", bold=True))
        click.echo("  `git config --global user.signingkey` is empty.")
        click.echo(f"  Set up commit signing per the handbook: {_POSTHOG_COMMIT_SIGNING_HANDBOOK_URL}")
        click.echo("  Then re-run `hogli devbox:setup --configure-git-signing`.")
        return

    if public_key.startswith("ssh-rsa "):
        click.echo()
        click.echo(click.style("RSA signing keys are not allowed.", fg="red"))
        click.echo(f"  Use ECDSA or Ed25519 per the handbook: {_POSTHOG_COMMIT_SIGNING_HANDBOOK_URL}")
        return

    upsert_user_secret(GIT_SIGNING_KEY_SECRET, public_key, env_name=GIT_SIGNING_KEY_SECRET)

    click.echo()
    click.echo(click.style("Git commit signing", bold=True))
    click.echo(f"  Pushed signing key from `git config user.signingkey`: {public_key}")
    agent_socket = _resolve_local_identity_agent_for_coder()
    if agent_socket:
        click.echo(f"  IdentityAgent for Coder hosts (from your ssh config): {agent_socket}")
    else:
        click.echo("  No IdentityAgent detected for Coder hosts -- SSH agent forwarding will use")
        click.echo(f"  whatever `$SSH_AUTH_SOCK` points to. Configure per: {_POSTHOG_COMMIT_SIGNING_HANDBOOK_URL}")
    click.echo()
    click.echo(click.style("If you haven't already:", bold=True))
    click.echo("  1. Open https://github.com/settings/ssh/new")
    click.echo("  2. Set 'Key type' to 'Signing Key' (auth keys do not sign).")
    click.echo("  3. Paste the key above.")
    click.echo()
    click.echo("Restart any running devbox (`hogli devbox:restart`) to pick up the new gitconfig.")


def _saved_region() -> str | None:
    """Return the saved region preference, or ``None`` when absent or invalid.

    A persisted value that's no longer in ``REGIONS`` (e.g. a stale entry
    from a hand-edited config) reads as unset instead of poisoning every
    downstream lookup.
    """
    saved = load_config().get("region")
    return saved if saved in REGIONS else None


def _preferred_region() -> str:
    """Return the saved preferred region, falling back to ``DEFAULT_REGION``.

    Centralized so every command path that needs the user's region
    preference reads the same value -- and so the fallback to the built-in
    default lives in one place.
    """
    return _saved_region() or DEFAULT_REGION


def maybe_configure_region(configure_region: bool | None) -> None:
    """Optionally persist the preferred region for new devboxes.

    The region is create-only on a workspace, so saving it locally just
    pre-fills ``devbox:start --region`` and determines the default
    workspace name (eu-central-1 boxes carry an ``-eu`` suffix). Existing
    workspaces are untouched.
    """
    config = load_config()
    existing_region = config.get("region")

    if configure_region is False:
        if not existing_region:
            click.echo("Skipping region preference setup.")
        return

    if configure_region is None and existing_region:
        return

    click.echo()
    click.echo(click.style("Preferred region", bold=True))
    click.echo("  Choose which region new devboxes should land in.")
    click.echo("  This is saved locally and used as the default for `hogli devbox:start`.")
    if existing_region:
        click.echo(f"  Current: {existing_region}")
    click.echo()

    default_region = existing_region or DEFAULT_REGION
    region = click.prompt(
        "Preferred region",
        default=default_region,
        type=click.Choice(REGIONS),
        show_choices=True,
        show_default=True,
    ).strip()

    save_region(region)
    click.echo(f"Saved preferred region: {region}")


def maybe_configure_dotfiles(configure_dotfiles: bool | None) -> None:
    """Optionally persist a dotfiles repo URL for new workspaces."""
    config = load_config()
    existing_uri = config.get("dotfiles_uri")

    if configure_dotfiles is False:
        if not existing_uri:
            click.echo("Skipping dotfiles setup.")
        return

    if configure_dotfiles is None and existing_uri:
        return

    click.echo()
    click.echo(click.style("Dotfiles (optional)", bold=True))
    click.echo("  Personalize your workspace with a dotfiles repository.")
    click.echo("  The repo will be cloned and applied on every workspace start.")
    click.echo("  This will be saved and reused for future workspaces.")
    if existing_uri:
        click.echo("  Press Enter to keep the current URL, or type a new one.")
        click.echo("  To remove dotfiles entirely, run `hogli devbox:config:rm dotfiles`.")
    click.echo()

    dotfiles_uri = click.prompt(
        "Dotfiles repo URL",
        default=existing_uri or "",
        show_default=bool(existing_uri),
    ).strip()

    if dotfiles_uri:
        save_dotfiles_uri(dotfiles_uri)
        click.echo(f"Saved dotfiles repo for new workspaces: {dotfiles_uri}")
    else:
        click.echo("No dotfiles repo configured.")


def _doctor_check(label: str, ok: bool) -> None:
    """Print one read-only doctor check line."""
    mark = click.style("ok", fg="green") if ok else click.style("missing", fg="red")
    click.echo(f"  [{mark}] {label}")


def _doctor_footer() -> None:
    """Point at the deterministic fix and the guided (agentic) one."""
    click.echo()
    click.echo("  Fix setup:    hogli devbox:setup")
    click.echo("  Guided setup: run the `setting-up-devbox` skill in your coding agent")


@click.command(name="devbox:doctor", help="Diagnose devbox prerequisites and setup (read-only).")
def devbox_doctor() -> None:
    """Read-only health check: tailnet access, Coder reachability, auth, saved setup.

    Safe for an agent to run as a probe -- it never prompts or mutates host
    config the way `devbox:setup` does. Run it first when a devbox command
    fails, and as step zero of the `setting-up-devbox` skill. The tailnet ACL
    grant is the prerequisite people most often miss, so it is surfaced
    explicitly whenever the control plane is unreachable.
    """
    click.echo(click.style("Devbox doctor", bold=True))
    click.echo(f"  Coder URL: {get_coder_url()}")
    click.echo()

    _doctor_check("Tailscale connected", tailscale_connected())

    reachable = coder_reachable()
    _doctor_check("Coder control plane reachable", reachable)

    if not reachable:
        diagnosis = _diagnose_unreachable_coder()
        click.echo()
        click.echo(click.style(f"  Cause: {diagnosis.cause}", fg="yellow"))
        click.echo(f"  Next:  {diagnosis.next_step}")
        for fact in diagnosis.facts:
            click.echo(f"    - {fact}")
        click.echo()
        click.echo(click.style("  Prerequisite:", bold=True))
        click.echo(f"    {_TAILNET_ACCESS_PREREQ}")
        _doctor_footer()
        return

    installed = coder_installed()
    _doctor_check("coder CLI installed", installed)
    authenticated = installed and coder_authenticated()
    _doctor_check("Coder authenticated", authenticated)
    # The Host coder.* block is a wildcard, so any name probes whether
    # `coder config-ssh` has run -- the prerequisite for devbox:ssh/exec.
    _doctor_check("SSH access configured (devbox:ssh/exec)", coder_ssh_alias_configured("probe"))

    if not authenticated:
        _doctor_footer()
        return

    # _print_setup_status emits its own "Currently configured:" header when
    # anything is set; only print a fallback line when it stays silent.
    if not _print_setup_status(_collect_setup_status()):
        click.echo()
        click.echo("Nothing configured yet.")
    _doctor_footer()


@click.command(name="devbox", help="Show available devbox commands")
def devbox_help() -> None:
    """Show the available `hogli devbox:*` commands."""
    manifest_obj = get_manifest()
    commands = sorted(
        (name, (manifest_obj.get_command_config(name) or {}).get("description", ""))
        for name in manifest_obj.get_all_commands()
        if name.startswith("devbox:") and not manifest_obj.is_command_hidden(name)
    )
    click.echo("Available devbox commands:")
    click.echo()
    for name, help_text in commands:
        click.echo(f"  hogli {name:<20} {help_text}")
    click.echo()
    click.echo("Run `hogli <command> --help` for command-specific options.")


def maybe_configure_claude_secret(configure_claude: bool | None, *, known_secret_names: set[str] | None = None) -> None:
    """Manage the ``CLAUDE_CODE_OAUTH_TOKEN`` Coder user secret for this user.

    Resolution order:

    1. Server unsupported (< 2.33) -- skip with a one-line note.
    2. Secret already exists and the user did not pass --configure-claude -- skip.
    3. Legacy macOS Keychain entry exists -- offer to migrate, then delete it.
    4. Otherwise -- prompt for a fresh token and create the secret.
    """
    if not server_supports_user_secrets():
        click.echo("Claude token: skipping (Coder server is older than 2.33; user secrets unavailable).")
        return

    if configure_claude is False:
        click.echo("Skipping Claude token setup.")
        return

    secret_exists = (
        CLAUDE_CODE_OAUTH_ENV in known_secret_names if known_secret_names is not None else has_claude_oauth_secret()
    )

    if secret_exists and configure_claude is not True:
        return

    legacy_token = _read_legacy_keychain_token()

    if legacy_token and not secret_exists and configure_claude is not True:
        click.echo()
        click.echo(click.style("Claude Code: migrating Keychain token to a Coder user secret", bold=True))
        click.echo("  hogli now stores the Claude OAuth token as a Coder user secret so that")
        click.echo("  workspaces -- and devbox:task runs -- pick it up automatically.")
        if click.confirm("Migrate the existing Keychain entry now?", default=True):
            upsert_user_secret(
                CLAUDE_CODE_OAUTH_ENV,
                legacy_token,
                env_name=CLAUDE_CODE_OAUTH_ENV,
                description="Claude Code OAuth token (managed by hogli)",
            )
            if _delete_legacy_keychain_token():
                click.echo("Migrated to Coder user secret. Removed the legacy Keychain entry.")
            else:
                click.echo("Migrated to Coder user secret. (Could not remove the legacy Keychain entry.)")
            return

    click.echo()
    click.echo(click.style("Claude Code (optional)", bold=True))
    click.echo("  Workspaces and devbox:task runs can use Claude Code if you provide an OAuth token.")
    click.echo("  The token will be stored as a Coder user secret and injected as")
    click.echo(f"  ${CLAUDE_CODE_OAUTH_ENV} into every workspace you start.")
    click.echo("  To generate one, run `claude setup-token` in another terminal.")
    click.echo()

    token = _prompt_for_claude_token()
    if not token:
        click.echo("No token provided. Skipping.")
        return

    upsert_user_secret(
        CLAUDE_CODE_OAUTH_ENV,
        token,
        env_name=CLAUDE_CODE_OAUTH_ENV,
        description="Claude Code OAuth token (managed by hogli)",
    )
    click.echo(f"Saved Claude token as Coder user secret '{CLAUDE_CODE_OAUTH_ENV}'.")


def _reset_user_secret(secret_name: str) -> bool:
    """Delete a Coder user secret. Returns True iff something was actually removed."""
    if delete_user_secret(secret_name).returncode == 0:
        click.echo(f"Deleted Coder user secret '{secret_name}'.")
        return True
    click.echo(f"Nothing to delete: '{secret_name}' was not set.")
    return False


def _reset_git_identity() -> bool:
    """Drop the saved Git name/email. Returns True iff something was cleared."""
    config = load_config()
    if not (config.get("git_name") or config.get("git_email")):
        click.echo("Nothing to clear: Git identity was not set.")
        return False
    clear_git_identity(config)
    click.echo("Cleared saved Git identity. New workspaces will prompt for one.")
    return True


def _reset_region() -> bool:
    """Drop the saved region preference. Returns True iff something was cleared."""
    config = load_config()
    if not config.get("region"):
        click.echo("Nothing to clear: region preference was not set.")
        return False
    clear_region(config)
    click.echo("Cleared saved region preference. New workspaces will use the built-in default.")
    return True


def _reset_dotfiles() -> bool:
    """Drop the saved dotfiles URI and push an empty parameter to existing workspaces.

    Clearing the local config alone only affects future workspaces -- existing
    workspaces keep cloning the old URL until the template parameter is overridden.

    Returns True iff something was cleared.
    """
    config = load_config()
    if not config.get("dotfiles_uri"):
        click.echo("Nothing to clear: dotfiles was not set.")
        return False
    clear_dotfiles_uri(config)
    click.echo("Cleared saved dotfiles repo. Pushing empty parameter to existing workspaces...")
    for ws in list_user_workspaces():
        ws_name = ws.get("name")
        if isinstance(ws_name, str) and ws_name:
            update_workspace_parameters(ws_name, {DOTFILES_URI_PARAMETER: ""})
            click.echo(f"  reset on '{ws_name}'")
    return True


def _git_identity_status(config: DevboxConfig, _: set[str]) -> str | None:
    name = config.get("git_name")
    email = config.get("git_email")
    return f"{name} <{email}>" if name and email else None


def _field_status(field: str) -> Callable[[DevboxConfig, set[str]], str | None]:
    """Status reader that returns a single config field's value (or ``None``)."""
    return lambda config, _: config.get(field)


def _secret_status(secret_name: str) -> Callable[[DevboxConfig, set[str]], str | None]:
    return lambda _config, secret_names: "configured" if secret_name in secret_names else None


@dataclass(frozen=True)
class _ConfigItem:
    """One row in the devbox setup status / reset table.

    Each item carries everything the status, show, and rm paths need:
    the CLI key (``devbox:config:rm <key>``), the human label
    (``devbox:config:show`` and the setup wizard's "Currently configured:"
    block), how to derive the current value from local config plus the
    set of Coder secret names, how to clear it, and whether clearing
    touches Coder user secrets (so the server-version check fires only
    when needed). New configurables land as one entry below.
    """

    cli_key: str
    label: str
    needs_secrets: bool
    status: Callable[[DevboxConfig, set[str]], str | None]
    reset: Callable[[], bool]


_CONFIG_ITEMS: tuple[_ConfigItem, ...] = (
    _ConfigItem(
        cli_key="git-identity",
        label="Git identity",
        needs_secrets=False,
        status=_git_identity_status,
        reset=_reset_git_identity,
    ),
    _ConfigItem(
        cli_key="git-signing",
        label="Git signing",
        needs_secrets=True,
        status=_secret_status(GIT_SIGNING_KEY_SECRET),
        reset=lambda: _reset_user_secret(GIT_SIGNING_KEY_SECRET),
    ),
    _ConfigItem(
        cli_key="region",
        label="Region",
        needs_secrets=False,
        status=_field_status("region"),
        reset=_reset_region,
    ),
    _ConfigItem(
        cli_key="dotfiles",
        label="Dotfiles",
        needs_secrets=False,
        status=_field_status("dotfiles_uri"),
        reset=_reset_dotfiles,
    ),
    _ConfigItem(
        cli_key="claude",
        label="Claude token",
        needs_secrets=True,
        status=_secret_status(CLAUDE_CODE_OAUTH_ENV),
        reset=lambda: _reset_user_secret(CLAUDE_CODE_OAUTH_ENV),
    ),
)


def _config_items_by_key() -> dict[str, _ConfigItem]:
    return {item.cli_key: item for item in _CONFIG_ITEMS}


def _fetch_secret_names() -> set[str]:
    """Bulk-fetch user-secret names in a single ``coder secret list`` round trip.

    ``None`` (older servers without user-secret support) maps to an empty set,
    matching the "no secrets" path. The result is safe to share across status
    rows and configure helpers within one CLI invocation.
    """
    secrets = list_user_secrets() or []
    return {name for s in secrets if isinstance(s, dict) and (name := s.get("name"))}


def _collect_setup_status(secret_names: set[str] | None = None) -> list[tuple[str, str | None]]:
    """Return one ``(label, value)`` tuple per configurable item.

    Pass ``secret_names`` to reuse a pre-fetched set when the caller already
    has one (the setup wizard does); otherwise we make our own ``coder secret
    list`` call so single-shot uses like ``devbox:config:show`` stay self-contained.
    """
    config = load_config()
    secrets = _fetch_secret_names() if secret_names is None else secret_names
    return [(item.label, item.status(config, secrets)) for item in _CONFIG_ITEMS]


def _print_setup_status(status: list[tuple[str, str | None]]) -> bool:
    """Render the compact status block. Returns True iff anything was printed.

    Stays silent when nothing is set yet so the wizard's first-run output
    isn't padded with "not set" lines; ``devbox:config:show`` uses the
    return value to choose between the block and a "Nothing configured yet"
    hint instead.
    """
    if not any(value for _, value in status):
        return False
    width = max(len(label) for label, _ in status) + 1
    click.echo()
    click.echo("Currently configured:")
    for label, value in status:
        rendered = value if value else click.style("not set", fg="yellow")
        click.echo(f"  {label:<{width}} {rendered}")
    return True


def _explicit_option_flag_passed(configure_flags: list[bool | None]) -> bool:
    """Return whether the user passed any explicit --configure-* / --skip-configure-* flag."""
    return any(flag is not None for flag in configure_flags)


def _confirm_run_setup() -> bool:
    """Show a Y/n gate explaining what setup will do. ``True`` means proceed.

    Skipped for non-interactive stdin so CI / piped invocations never block.
    """
    if not sys.stdin.isatty():
        return True
    click.echo()
    click.echo("hogli devbox:setup will check or configure:")
    click.echo("  - Tailscale + Coder reachability")
    click.echo("  - Local SSH config for Coder hosts")
    click.echo("  - File sync tooling (mutagen) for devbox:sync")
    click.echo("  - Git identity (name/email) for new workspaces")
    click.echo("  - Git commit signing key propagation")
    click.echo("  - Preferred region for new workspaces (optional)")
    click.echo("  - Dotfiles repo for new workspaces (optional)")
    click.echo("  - Claude OAuth token as a Coder user secret (optional)")
    click.echo()
    return click.confirm("Proceed?", default=True)


@click.command(name="devbox:setup", help="Install and configure local access to Coder devboxes")
@click.option(
    "--configure-ssh/--skip-configure-ssh",
    default=None,
    help="Configure local SSH host entries for Coder workspaces during setup",
)
@click.option(
    "--configure-git-identity/--skip-configure-git-identity",
    default=None,
    help="Prompt for Git name/email defaults for new Coder workspaces",
)
@click.option(
    "--configure-git-signing/--skip-configure-git-signing",
    default=None,
    help="Propagate your local git signing key into Coder devboxes (reads git config user.signingkey)",
)
@click.option(
    "--configure-region/--skip-configure-region",
    default=None,
    help="Prompt for the preferred region (us-east-1 or eu-central-1) for new devboxes",
)
@click.option(
    "--configure-dotfiles/--skip-configure-dotfiles",
    default=None,
    help="Prompt for a dotfiles repo URL for new Coder workspaces",
)
@click.option(
    "--configure-claude/--skip-configure-claude",
    "configure_claude_setup",
    default=None,
    help="Manage the CLAUDE_CODE_OAUTH_TOKEN Coder user secret for this user",
)
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_setup(
    configure_ssh: bool | None,
    configure_git_identity: bool | None,
    configure_git_signing: bool | None,
    configure_region: bool | None,
    configure_dotfiles: bool | None,
    configure_claude_setup: bool | None,
    verbose: bool,
) -> None:
    """Prepare this machine for Coder workspaces."""
    explicit = _explicit_option_flag_passed(
        [
            configure_ssh,
            configure_git_identity,
            configure_git_signing,
            configure_region,
            configure_dotfiles,
            configure_claude_setup,
        ],
    )

    click.echo(click.style("Configuring devbox CLI access...", bold=True))
    ensure_tailscale_connected("rerun `hogli devbox:setup`.")
    ensure_tailscale_routes_accepted()
    ensure_coder_reachable()
    ensure_coder_installed(verbose=verbose)
    ensure_coder_authenticated()

    # One `coder secret list` round trip fuels the status block and both
    # secret-aware configure helpers. None of the upcoming steps mutate a
    # secret the *other* steps' checks care about, so the snapshot stays
    # valid for the duration of this invocation.
    secret_names = _fetch_secret_names()

    status = _collect_setup_status(secret_names)
    _print_setup_status(status)

    if not explicit and not _confirm_run_setup():
        click.echo("Aborted. Re-run `hogli devbox:setup` when ready.")
        return

    mutagen.ensure_mutagen_installed(verbose=verbose)
    mutagen.ensure_daemon_with_shim()
    click.echo(
        "  Note: the mutagen daemon is left unregistered from login auto-start so devbox "
        "sync can apply its ssh keepalive fix; it starts on demand the next time you sync."
    )
    mutagen.ensure_user_mutagen_config()
    maybe_configure_ssh(
        configure_ssh=configure_ssh,
        identity_agent_socket=_resolve_local_identity_agent_for_coder(),
        verbose=verbose,
    )
    maybe_configure_git_identity(configure_git_identity)
    maybe_configure_git_signing(configure_git_signing, known_secret_names=secret_names)
    maybe_configure_region(configure_region)
    maybe_configure_dotfiles(configure_dotfiles)
    maybe_configure_claude_secret(configure_claude_setup, known_secret_names=secret_names)
    print_setup_summary()


@click.command(name="devbox:list", help="List your devboxes")
def devbox_list() -> None:
    """List all workspaces belonging to the current user, plus shared workspaces."""
    ensure_runtime_ready()
    workspaces = list_user_workspaces()

    if not workspaces:
        click.echo("No devboxes found. Run 'hogli devbox:start' to create one.")
    else:
        click.echo(f"{'LABEL':<16} {'STATUS':<12} {'REGION':<14} {'SYNC':<18} {'NAME'}")
        for ws in workspaces:
            ws_name = ws.get("name", "")
            label = extract_workspace_label(ws_name) or "(default)"
            status = get_workspace_status(ws)
            region = get_workspace_region(ws) or "unknown"
            styled_status = click.style(status, fg=_workspace_status_color(status))
            sync_state = _render_sync_status(ws_name)
            click.echo(
                f"  {label:<14} {_ljust_styled(styled_status, 12)} "
                f"{region:<14} {_ljust_styled(sync_state, 18)} {ws_name}"
            )

    shared = list_shared_workspaces()
    if shared:
        click.echo()
        click.echo("Shared with you:")
        for ws in shared:
            ws_name = ws.get("name", "")
            status = get_workspace_status(ws)
            owner = ws.get("owner_name", "unknown")
            click.echo(f"  {ws_name:<30} {click.style(status, fg=_workspace_status_color(status)):<20} (from {owner})")

    shared_out: list[tuple[str, list[str]]] = []
    for ws in workspaces:
        ws_name = ws.get("name", "")
        users = get_shared_users(ws_name)
        if users:
            shared_out.append((ws_name, users))
    if shared_out:
        click.echo()
        click.echo("Shared with others:")
        for ws_name, users in shared_out:
            label = extract_workspace_label(ws_name) or "(default)"
            click.echo(f"  {label:<16} {', '.join(users)}")


@click.command(name="devbox:users", help="List Coder users (for devbox sharing)")
def devbox_users() -> None:
    """List all active Coder users so you know who to share with."""
    ensure_runtime_ready()

    current_user = get_coder_user_info()
    current_username = current_user.get("username", "")

    users = list_coder_users()
    if not users:
        _fail("Could not fetch users. Check your Coder authentication.")

    users.sort(key=lambda u: u.get("username", ""))

    click.echo(f"  {'USERNAME':<16} {'NAME':<30} {'EMAIL'}")
    for user in users:
        username = user.get("username", "")
        name = user.get("name", "")
        email = user.get("email", "")
        is_you = username == current_username
        name_col = f"{'(you)' if is_you else name:<30}"
        if is_you:
            name_col = click.style(name_col, fg="green")
        click.echo(f"  {username:<16} {name_col} {email}")


def _hint_if_positional_looks_like_username(
    command: str, workspace: str | None, users: tuple[str, ...], list_sharing: bool = False
) -> None:
    """Warn when the positional arg is almost certainly meant as a target username.

    The positional slot on every `devbox:*` command selects a workspace label,
    not a user. Share/unshare take `--user` for the target, so this case is a
    common footgun.
    """
    if workspace and not users and not list_sharing:
        raise click.UsageError(
            f"Pass the target user with --user (e.g. `hogli {command} --user {workspace}`).\n"
            "The positional argument selects one of YOUR workspaces. Run 'hogli devbox:users' to find usernames."
        )


@click.command(name="devbox:share", help="Share your devbox with other users")
@workspace_argument
@click.option("--user", "users", multiple=True, help="Coder username(s) to share with")
@click.option("--role", type=click.Choice(["use", "admin"]), default="use", help="Access role to grant")
@click.option("--list", "list_sharing", is_flag=True, help="Show who has access")
def devbox_share(
    workspace: str | None,
    users: tuple[str, ...],
    role: str,
    list_sharing: bool,
) -> None:
    """Share your devbox with other Coder users."""
    ensure_runtime_ready()
    _hint_if_positional_looks_like_username("devbox:share", workspace, users, list_sharing)

    name, workspaces = resolve_workspace_name(workspace)
    _get_workspace_or_fail(name, workspaces)

    if list_sharing:
        result = get_sharing_status(name)
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        click.echo(result.stdout)
        return

    if not users:
        raise click.UsageError("Specify at least one --user. Run 'hogli devbox:users' to find usernames.")

    share_workspace(name, list(users), role)
    click.echo(f"Shared '{name}' with {', '.join(users)} (role: {role}).")


@click.command(name="devbox:unshare", help="Revoke access to your devbox from other users")
@workspace_argument
@click.option("--user", "users", multiple=True, help="Coder username(s) to revoke access from")
def devbox_unshare(workspace: str | None, users: tuple[str, ...]) -> None:
    """Revoke access to your devbox from one or more Coder users."""
    ensure_runtime_ready()
    _hint_if_positional_looks_like_username("devbox:unshare", workspace, users)

    name, workspaces = resolve_workspace_name(workspace)
    _get_workspace_or_fail(name, workspaces)

    if not users:
        raise click.UsageError("Specify at least one --user. Run 'hogli devbox:share --list' to see current access.")

    user_list = list(users)
    unshare_workspace(name, user_list)
    click.echo(f"Revoked access for: {', '.join(user_list)}")
    click.echo(click.style("Restart your devbox for this to take effect.", fg="yellow"))


def _maybe_hint_region_mismatch(name: str) -> None:
    """On resuming a default box outside the saved region pref, say how to get one there.

    Quiet for labeled boxes -- the pref only governs the default box. Callers
    gate on a bare invocation (a label or ``--region`` is already a deliberate
    choice).
    """
    saved = _saved_region()
    if saved is None or extract_workspace_label(name) is not None:
        return
    box_region = region_from_workspace_name(name)
    if box_region != saved:
        click.echo(
            f"Your devbox '{name}' is in {box_region}, but your saved region is {saved}. "
            f"Create a {saved} devbox with `hogli devbox:start --region {saved}`."
        )


@click.command(name="devbox:start", help="Start or create your remote devbox")
@workspace_argument
@click.option(
    "--disk",
    type=click.Choice(["60", "80", "100"]),
    default="100",
    help="Disk size in GiB (default: 100)",
)
@click.option(
    "-t",
    "--template",
    default=DEFAULT_TEMPLATE,
    show_default=True,
    help="Coder workspace template to use when creating a new devbox",
)
@click.option(
    "-p",
    "--preset",
    default=DEFAULT_PRESET,
    show_default=True,
    help="Coder template preset to apply (use 'none' to opt out)",
)
@click.option(
    "--region",
    type=click.Choice(REGIONS),
    default=None,
    help=(
        "Region whose default devbox to start, creating it if needed (a devbox's region is "
        "set at creation and cannot change). Defaults to the value saved by "
        "`devbox:setup --configure-region`, then us-east-1."
    ),
)
@click.option(
    "--start-app/--no-start-app",
    "start_app",
    default=None,
    help=(
        "Bring the PostHog app up in the background on every workspace start. "
        "Sticky on the workspace until flipped with --no-start-app."
    ),
)
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_start(
    workspace: str | None,
    disk: str,
    template: str,
    preset: str,
    region: str | None,
    start_app: bool | None,
    verbose: bool,
) -> None:
    """Start or create the remote devbox."""
    ensure_runtime_ready()
    effective_region = region or _preferred_region()
    if workspace is None and region is not None:
        # An explicit --region targets that region's default directly, so it
        # can be created (or resumed) regardless of boxes in other regions.
        name = get_workspace_name(region=effective_region)
        workspaces: list[dict[str, Any]] | None = list_user_workspaces()
    else:
        # Resolution prefers the effective region's default but falls back to
        # the box the user already has -- a saved pref alone never abandons it.
        name, workspaces = resolve_workspace_name(workspace, region=effective_region)
    ws = get_workspace(name, workspaces)

    if ws is not None:
        if workspace is None and region is None:
            _maybe_hint_region_mismatch(name)
        _start_existing_workspace(name, ws, start_app=start_app, verbose=verbose)
        return

    config = load_config()

    click.echo(
        f"Creating devbox '{name}' (template={template}, preset={preset}, region={effective_region}, disk={disk}GiB)..."
    )
    create_workspace(
        name,
        int(disk),
        git_name=config.get("git_name"),
        git_email=config.get("git_email"),
        dotfiles_uri=config.get("dotfiles_uri"),
        region=effective_region,
        template=template,
        preset=preset,
        start_app=start_app,
        verbose=verbose,
    )
    click.echo("Created.")
    _print_connection_info(name)


@click.command(
    name="devbox:clone",
    help="Clone a running devbox into a new one, carrying its full disk state",
)
@workspace_argument
@click.option(
    "--as",
    "new_label",
    default="clone",
    show_default=True,
    help="Label for the new devbox (becomes devbox-<you>-<label>)",
)
@click.option("-y", "--yes", is_flag=True, help="Skip the confirmation prompt")
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_clone(workspace: str | None, new_label: str, yes: bool, verbose: bool) -> None:
    """Duplicate a running devbox, disk and all.

    Captures the source box's root volume into a private, short-lived AMI and
    boots a new devbox from it, so the clone comes up with the source's full
    disk state -- uncommitted work, local databases, installed tooling -- not
    just the settings that dotfiles and user secrets already carry. The source
    must be running; quiesce its dev stack first for an application-consistent
    copy. The capture image is private to you and auto-expires.
    """
    ensure_runtime_ready()
    source_name, workspaces = resolve_workspace_name(workspace)
    ws = _get_workspace_or_fail(source_name, workspaces)

    owner = get_username()
    if str(ws.get("owner_name") or "").lower() not in ("", owner):
        _fail("You can only clone your own devbox.")

    template = ws.get("template_name") or DEFAULT_TEMPLATE
    if template != DEFAULT_TEMPLATE:
        _fail(f"Clone supports the '{DEFAULT_TEMPLATE}' template only (this devbox uses '{template}').")

    # The clone lands in the source's region -- a per-clone AMI is region-scoped,
    # so the template images and boots within that same region.
    region = region_from_workspace_name(source_name)

    status = get_workspace_status(ws)
    if status != "running":
        suffix = _workspace_arg_suffix(source_name)
        _fail(
            f"The source devbox must be running to clone it (status: {status}). Start it: `hogli devbox:start{suffix}`."
        )

    target_name = get_workspace_name(new_label, region=region)
    if get_workspace(target_name, workspaces) is not None:
        _fail(f"A devbox named '{target_name}' already exists. Pass `--as <label>` to pick another name.")

    if not yes:
        click.echo(f"Clone '{source_name}' -> '{target_name}'.")
        click.echo(
            "This images the source box's entire disk (including any on-disk secrets) into a\n"
            "private AMI and boots the new box from it. The image auto-expires after a few days."
        )
        if not click.confirm("Proceed?"):
            click.echo("Cancelled.")
            return

    disk_size = get_workspace_disk_size(ws)
    if disk_size is None:
        _fail("Could not determine the source devbox's disk size. Rebuild it on the latest template and retry.")

    source_instance_id = get_source_instance_id(source_name)
    click.echo(
        f"Cloning '{source_name}' ({source_instance_id}) -> '{target_name}'. "
        "The template captures its disk into a private image (a few minutes) and boots the clone from it."
    )
    clone_workspace(
        target_name,
        source_instance_id=source_instance_id,
        disk_size=disk_size,
        region=region,
        template=template,
        verbose=verbose,
    )
    click.echo("Cloned.")
    _print_connection_info(target_name)


@click.command(name="devbox:stop", help="Stop your devbox (preserves disk, stops billing)")
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_stop(workspace: str | None, verbose: bool) -> None:
    """Stop the devbox. State is preserved on the EBS volume."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)
    ws = _get_workspace_or_fail(name, workspaces)

    status = get_workspace_status(ws)
    if status == "stopped":
        click.echo(f"Devbox '{name}' is already stopped.")
        return

    click.echo(f"Stopping '{name}'...")
    stop_workspace(name, verbose=verbose)
    click.echo("Stopped. Disk preserved. Run 'hogli devbox:start' to resume.")


@click.command(name="devbox:restart", help="Restart your devbox")
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_restart(workspace: str | None, verbose: bool) -> None:
    """Stop and start the devbox in one step."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)
    _get_workspace_or_fail(name, workspaces)
    click.echo(f"Restarting '{name}'...")
    restart_workspace(name, verbose=verbose)
    click.echo("Restarted.")
    _print_connection_info(name)


@click.command(name="devbox:update", help="Update devbox to the latest template")
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_update(workspace: str | None, verbose: bool) -> None:
    """Apply the latest template to the devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)
    ws = _get_workspace_or_fail(name, workspaces)
    if not ws.get("outdated"):
        click.echo(f"Devbox '{name}' is already up to date.")
        return
    config = load_config()
    params: dict[str, str] = {}
    if dotfiles_uri := config.get("dotfiles_uri"):
        params[DOTFILES_URI_PARAMETER] = dotfiles_uri
    click.echo(f"Updating '{name}' to the latest template...")
    update_workspace(name, parameters=params, verbose=verbose)
    click.echo("Updated.")
    click.echo(
        "Note: if your local lockfiles differ from the new AMI's baked versions, "
        "expect a one-time dep re-install on next workspace start (2-5 min)."
    )
    _print_connection_info(name)


@click.command(name="devbox:ssh", help="SSH into your devbox")
@workspace_argument
def devbox_ssh(workspace: str | None) -> None:
    """Open an SSH session to the devbox."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    ssh_replace(name)


@click.command(
    name="devbox:exec",
    help="Run a command inside your devbox (non-interactive).",
    context_settings={"ignore_unknown_options": True},
)
@click.option("--name", "-n", "workspace_name", default=None, help="Workspace label or @user[/label] target")
@click.argument("command", nargs=-1, type=click.UNPROCESSED, required=True)
def devbox_remote_exec(workspace_name: str | None, command: tuple[str, ...]) -> None:
    """Run COMMAND in the devbox over `coder ssh` and propagate its exit code.

    Unlike `devbox:ssh`, this runs a single command instead of opening an
    interactive shell, so agents and scripts can drive a devbox remotely:

        hogli devbox:exec -- gh auth status
        hogli devbox:exec -n api -- bash -lc 'cd ~/posthog && git status'

    Use `--` to separate hogli's flags from the command's own flags.
    """
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace_name)
    if not coder_ssh_alias_configured(name):
        _fail(
            "SSH access for devboxes isn't configured. Run `hogli devbox:setup` (it runs `coder config-ssh`), then retry."
        )
    exec_replace(name, list(command))


@click.command(name="devbox:open", help="Open devbox in browser, VS Code, or Cursor")
@workspace_argument
@click.option("--vscode", is_flag=True, help="Open in VS Code Desktop via SSH")
@click.option("--cursor", is_flag=True, help="Open in Cursor via SSH")
@click.option("--web", is_flag=True, help="Open code-server (VS Code in browser)")
def devbox_open(workspace: str | None, vscode: bool, cursor: bool, web: bool) -> None:
    """Open the devbox in a browser or editor."""
    chosen = sum([vscode, cursor, web])
    if chosen > 1:
        raise click.UsageError("Choose one of `--vscode`, `--cursor`, or `--web`.")

    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)

    if (vscode or cursor) and mutagen.sync_list(label_selector=mutagen.workspace_label_selector(name)):
        ide = "VS Code" if vscode else "Cursor"
        click.echo(
            click.style(
                f"⚠ Sync is active for '{name}'. Editing in {ide} Remote can conflict with the local source of truth.",
                fg="yellow",
            )
        )

    if vscode:
        click.echo(f"Opening '{name}' in VS Code...")
        open_vscode(name)
    elif cursor:
        click.echo(f"Opening '{name}' in Cursor...")
        open_cursor(name)
    elif web:
        click.echo(f"Opening code-server for '{name}'...")
        open_web_ide(name)
    else:
        click.echo(f"Opening '{name}' in browser...")
        open_in_browser(name)


@click.command(name="devbox:logs", help="Tail devbox build and agent logs")
@workspace_argument
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
def devbox_logs(workspace: str | None, follow: bool) -> None:
    """Tail workspace build and agent logs."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    logs_replace(name, follow)


@click.command(name="devbox:task", short_help="Run a background agent task on a fresh devbox")
@click.argument("prompt", required=False)
@click.option("--name", "task_name", default=None, help="Task name (auto-generated if omitted)")
@click.option("-q", "--quiet", is_flag=True, help="Only print the created task's ID")
@click.option(
    "-t",
    "--template",
    default=DEFAULT_TEMPLATE,
    show_default=True,
    help="Coder workspace template to run the task on",
)
def devbox_task(prompt: str | None, task_name: str | None, quiet: bool, template: str) -> None:
    """Start a background Coder task on the chosen workspace template.

    The Coder deployment provisions a fresh workspace per task and hands the
    prompt to the agent configured in the template. Pass the prompt as a
    positional argument or pipe it via stdin.

    \b
    Examples:
      hogli devbox:task "fix CI on PR #1234"
      cat prompt.txt | hogli devbox:task
    """
    if prompt is None and click.get_text_stream("stdin").isatty():
        raise click.UsageError(
            "Provide a prompt as an argument, or pipe it via stdin.\n"
            'Example: hogli devbox:task "document the ingestion pipeline"'
        )
    ensure_runtime_ready()
    if server_supports_user_secrets() and not has_claude_oauth_secret():
        click.echo(
            click.style(
                f"Warning: no '{CLAUDE_CODE_OAUTH_ENV}' Coder user secret set; the task will run without Claude auth.",
                fg="yellow",
            ),
            err=True,
        )
        click.echo(
            "  Run `hogli devbox:setup --configure-claude` (or `hogli devbox:secret:set "
            f"{CLAUDE_CODE_OAUTH_ENV}`) to set it.",
            err=True,
        )
    create_task(prompt, task_name=task_name, quiet=quiet, template=template)


def _ensure_user_secrets_supported() -> None:
    """Fail fast when the Coder server does not support user secrets."""
    if server_supports_user_secrets():
        return
    _fail("Coder server does not support user secrets (requires >= 2.33). Update the deployment first.")


@click.command(name="devbox:secret:list", help="List your Coder user secrets")
def devbox_secret_list() -> None:
    """List the user secrets attached to your Coder account."""
    ensure_runtime_ready()
    _ensure_user_secrets_supported()

    secrets = list_user_secrets()
    if secrets is None:
        _fail("Could not list user secrets. Check `coder secret list` directly for details.")
    if not secrets:
        click.echo("No user secrets configured. Run `hogli devbox:secret:set NAME` to add one.")
        return

    click.echo(f"  {'NAME':<32} {'ENV':<32} DESCRIPTION")
    for secret in secrets:
        name = str(secret.get("name", ""))
        env = str(secret.get("env_name") or secret.get("env") or "")
        description = str(secret.get("description", ""))
        click.echo(f"  {name:<32} {env:<32} {description}")


@click.command(name="devbox:secret:set", help="Create or replace a Coder user secret")
@click.argument("name")
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    default=None,
    help="Read the secret value from this file instead of prompting for it",
)
@click.option(
    "--env",
    "env_name",
    default=None,
    help="Environment variable name to inject in the workspace (defaults to NAME)",
)
@click.option("--description", default=None, help="Optional description")
def devbox_secret_set(name: str, file_path: Path | None, env_name: str | None, description: str | None) -> None:
    """Set a Coder user secret. Replaces any existing secret with the same name."""
    ensure_runtime_ready()
    _ensure_user_secrets_supported()

    target_env = env_name or name

    if file_path is not None:
        value = file_path.read_text().rstrip("\n")
    else:
        value = click.prompt(f"Value for {name}", hide_input=True, confirmation_prompt=True)
    if not value:
        _fail("Empty value rejected. Pass --file PATH or enter a non-empty value.")

    upsert_user_secret(name, value, env_name=target_env, description=description)
    click.echo(f"Set user secret '{name}' (env: {target_env}). Restart workspaces to pick up the change.")


@click.command(name="devbox:secret:rm", help="Delete a Coder user secret")
@click.argument("name")
def devbox_secret_rm(name: str) -> None:
    """Delete a Coder user secret by name."""
    ensure_runtime_ready()
    _ensure_user_secrets_supported()

    result = delete_user_secret(name)
    if result.returncode != 0:
        if result.stderr:
            click.echo(result.stderr.strip(), err=True)
        _fail(f"Failed to delete user secret '{name}'.")
    click.echo(f"Deleted user secret '{name}'.")


@click.command(name="devbox:config:show", help="Show saved devbox setup configuration")
def devbox_config_show() -> None:
    """Print the local devbox configuration saved by ``devbox:setup``."""
    ensure_runtime_ready()
    if not _print_setup_status(_collect_setup_status()):
        click.echo("Nothing configured yet. Run `hogli devbox:setup`.")


@click.command(name="devbox:config:rm", help="Clear saved devbox configuration items")
@click.argument("keys", nargs=-1)
@click.option("--all", "reset_all", is_flag=True, help="Clear every saved item")
def devbox_config_rm(keys: tuple[str, ...], reset_all: bool) -> None:
    """Remove one or more saved devbox configuration items.

    Valid keys mirror the matching ``--configure-*`` flags on ``devbox:setup``:
    ``git-identity``, ``git-signing``, ``region``, ``dotfiles``, ``claude``.
    """
    by_key = _config_items_by_key()
    valid_keys = tuple(by_key)

    if reset_all and keys:
        _fail("Pass --all or one or more keys, not both. Valid keys: " + ", ".join(valid_keys))
    if not reset_all and not keys:
        _fail("Pass at least one key, or --all. Valid keys: " + ", ".join(valid_keys))

    unknown = [k for k in keys if k not in by_key]
    if unknown:
        suffix = "s" if len(unknown) > 1 else ""
        _fail(f"Unknown key{suffix}: {', '.join(unknown)}. Valid keys: {', '.join(valid_keys)}")

    ensure_runtime_ready()
    targets = [by_key[k] for k in (valid_keys if reset_all else keys)]
    if any(item.needs_secrets for item in targets):
        _ensure_user_secrets_supported()

    # Materialize results so every handler runs even when only some clear anything.
    fired = [item.reset() for item in targets]
    if any(fired):
        click.echo()
        click.echo("Restart any running devbox (`hogli devbox:restart`) to pick up the resets.")


@click.command(name="devbox:destroy", help="Destroy your devbox and its data")
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_destroy(workspace: str | None, verbose: bool) -> None:
    """Destroy the devbox completely."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)

    ws = get_workspace(name, workspaces)
    if ws is None:
        click.echo("No devbox found.")
        return

    if not click.confirm(f"Destroy '{name}'? This deletes the VM and its data"):
        click.echo("Cancelled.")
        return

    label = mutagen.workspace_label_selector(name)
    if mutagen.sync_list(label_selector=label):
        try:
            mutagen.sync_terminate(label)
            click.echo("Sync session terminated.")
        except SystemExit:
            # Best-effort: a stuck mutagen daemon should not block the user
            # from destroying their devbox. The session ends with the remote.
            click.echo(click.style("Warning: failed to terminate sync session; continuing.", fg="yellow"))

    delete_workspace(name, verbose=verbose)
    click.echo("Destroyed.")


@click.command(name="devbox:status", help="Show devbox status")
@workspace_argument
def devbox_status(workspace: str | None) -> None:
    """Show the current state of the devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)

    ws = get_workspace(name, workspaces)
    if ws is None:
        click.echo("No devbox found. Run 'hogli devbox:start' to create one.")
        return

    status = get_workspace_status(ws)

    click.echo(f"  Name:    {name}")
    click.echo(f"  Status:  {click.style(status, fg=_workspace_status_color(status))}")
    click.echo(f"  Region:  {get_workspace_region(ws) or 'unknown'}")
    click.echo(f"  Sync:    {_render_sync_status(name)}")

    if ws.get("outdated"):
        click.echo(click.style("  Update:  template update available", fg="yellow"))
        click.echo("           Run `hogli devbox:update` to apply it.")

    # Show agent status if available
    resources = ws.get("latest_build", {}).get("resources", [])
    for resource in resources:
        for agent in resource.get("agents", []):
            agent_status = agent.get("status", "unknown")
            click.echo(f"  Agent:   {agent_status}")

    if status == "running":
        _print_connection_info(name)


@click.command(name="devbox:forward", help="Forward PostHog UI to localhost")
@workspace_argument
@click.option("--port", default=8010, type=int, help="Local port to forward to")
def devbox_forward(workspace: str | None, port: int) -> None:
    """Forward the PostHog UI port to localhost."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    if not _local_port_is_available(port):
        _fail(
            f"Local port {port} is already in use.\n"
            f"Stop the process using that port or rerun with `hogli devbox:forward --port {port + 1}`."
        )

    click.echo(f"Forwarding {name}:8010 -> localhost:{port}")
    click.echo(f"PostHog UI at http://localhost:{port}")
    click.echo("Ctrl+C to stop")
    click.echo()
    port_forward_replace(name, port, 8010)


def _gib(nbytes: int) -> str:
    return f"{nbytes / 1024**3:.1f}G"


def _snapshot_free(paths: list[Path]) -> dict[int, int]:
    """Return free bytes keyed by device ID, deduplicating paths on the same filesystem."""
    seen: dict[int, int] = {}
    for path in paths:
        try:
            dev = path.stat().st_dev
            if dev not in seen:
                seen[dev] = shutil.disk_usage(path).free
        except OSError:
            pass
    return seen


def _sum_freed(before: dict[int, int], after: dict[int, int]) -> int:
    """Sum free-space gains across all watched devices."""
    return sum(max(0, after[dev] - before[dev]) for dev in after if dev in before)


def _run_cleanup_step(label: str, cmd: list[str]) -> None:
    """Run a cleanup command and print its label."""
    click.echo(f"  {label}...", nl=False)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        click.echo(" done")
    except FileNotFoundError:
        click.echo(" skipped (command unavailable)")
    except subprocess.CalledProcessError as e:
        click.echo(f" warning: exited with code {e.returncode}")


def _rm_dir(label: str, path: Path) -> None:
    """Delete a directory and print its label."""
    if not path.exists():
        click.echo(f"  {label}... skipped (not found)")
        return
    click.echo(f"  {label}...", nl=False)
    try:
        shutil.rmtree(path)
        click.echo(" done")
    except OSError as e:
        click.echo(f" warning: partial deletion ({e})")


@click.command(name="devbox:cleanup:disk", help="Free disk space by cleaning caches and build artifacts")
@click.option("--docker", "prune_docker", is_flag=True, help="Also prune stopped Docker containers")
@click.option(
    "--cargo",
    "prune_cargo",
    is_flag=True,
    help="Also remove Cargo build artifacts (forces full Rust recompile on next build)",
)
def devbox_cleanup_disk(prune_docker: bool, prune_cargo: bool) -> None:
    """Free disk space by removing caches and build artifacts that are safe to delete.

    The default run is safe: it only removes orphaned packages, download caches,
    and old Nix generations — none of which force a full rebuild on next use.
    Use --cargo to also remove Cargo build artifacts (forces full Rust recompile).
    Use --docker to also prune stopped containers.
    """
    home = Path.home()
    # Watch distinct filesystems: home covers uv/sccache/cargo; /nix covers Nix store
    # (may be a separate volume); / covers Docker storage and anything else.
    watch_paths = [p for p in [home, Path("/nix"), Path("/")] if p.exists()]
    before = _snapshot_free(watch_paths)

    click.echo("Cleaning caches and build artifacts...")
    click.echo()

    # uv wheel/sdist cache
    _run_cleanup_step("uv cache (~/.cache/uv)", ["uv", "cache", "clean"])

    # sccache compiler cache
    _rm_dir("sccache (~/.cache/sccache)", home / ".cache" / "sccache")

    # pnpm orphaned store entries
    _run_cleanup_step("pnpm store (orphaned packages)", ["pnpm", "store", "prune"])

    click.echo("  Nix garbage collection (old generations)...", nl=False)
    try:
        subprocess.run(["nix-collect-garbage", "-d"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        click.echo(" done")
    except FileNotFoundError:
        click.echo(" skipped (nix-collect-garbage unavailable)")
    except subprocess.CalledProcessError as e:
        click.echo(f" warning: exited with code {e.returncode}")

    # Cargo build artifacts — opt-in because removing them forces a full Rust recompile
    if prune_cargo:
        _rm_dir("Cargo build artifacts (~/.cargo/target)", home / ".cargo" / "target")

    if prune_docker:
        click.echo("  Docker stopped containers...", nl=False)
        try:
            subprocess.run(
                ["docker", "container", "prune", "-f"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )  # noqa: S603
            click.echo(" done")
        except FileNotFoundError:
            click.echo(" skipped (docker unavailable)")
        except subprocess.CalledProcessError as e:
            click.echo(f" warning: exited with code {e.returncode}")

    actually_freed = _sum_freed(before, _snapshot_free(watch_paths))

    click.echo()
    if actually_freed > 0:
        click.echo(click.style(f"Freed {_gib(actually_freed)} of disk space.", fg="green"))
    else:
        click.echo("Nothing significant was freed (caches may already be empty).")

    tips = []
    if not prune_cargo:
        tips.append("  hogli devbox:cleanup:disk --cargo  (rm ~/.cargo/target, forces recompile)")
    if not prune_docker:
        tips.append("  hogli devbox:cleanup:disk --docker  (prune stopped containers)")
    if tips:
        click.echo()
        click.echo("Tips for more space:")
        for tip in tips:
            click.echo(tip)
