from __future__ import annotations

import os
import re
import sys
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import click
from hogli.manifest import REPO_ROOT

from hogli_commands import env_file, gateway, posthog_auth
from hogli_commands.devbox import coder

ENV = ".env"
ENV_LOCAL = ".env.local"
ENV_EXAMPLE = ".env.example"
DISABLE_MARKER = "# disabled by hogli tasks:setup: "
HEADER = "# Local Tasks sandboxes on Modal (written by hogli tasks:setup)"

PROVIDER = "MODAL_DOCKER"
GATEWAY_URL = "https://gateway.us.posthog.com"
GATEWAY_PRODUCT = "posthog_code"
TOKEN_KEY = "SANDBOX_AI_GATEWAY_DEV_TOKEN"
TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60
TOKEN_REFRESH_WINDOW = timedelta(days=1)
MODAL_KEYS = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
SECRET_KEYS = frozenset({*MODAL_KEYS, TOKEN_KEY})
OP_ITEM = "op://General/Modal Development Token"
OP_TIMEOUT_SECONDS = 30
LOCAL_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")
LEGACY_KEYS = ("SANDBOX_LLM_GATEWAY_URL", "SANDBOX_AI_GATEWAY_WORKER_URL")

MODAL_STEP = (
    "Fill in MODAL_TOKEN_ID and MODAL_TOKEN_SECRET from 'Modal Development Token' in the General vault of "
    "PostHog's 1Password, or install the 1Password CLI (`brew install 1password-cli`) and sign in, then re-run."
)
FUNNEL_STEP = (
    "Set SANDBOX_API_URL and SANDBOX_MCP_URL: connect Tailscale and re-run, "
    "or pass --funnel-host <machine>.<tailnet>.ts.net when the Funnel runs on another machine."
)
RESTART_HINT = (
    "Restart to pick these up: re-activate flox (this shell still holds the old .env values), "
    "then run `hogli stop && hogli up -d`."
)

_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")

Action = Literal["add", "update", "disable", "keep"]


@dataclass(frozen=True)
class Desired:
    value: str | None
    reason: str
    overwrite_ok: bool = False


@dataclass(frozen=True)
class Row:
    key: str
    file: str
    current: str | None
    new: str | None
    action: Action
    reason: str
    needs_force: bool = False


@dataclass(frozen=True)
class Plan:
    rows: tuple[Row, ...]
    remaining: Mapping[str, str]
    funnel_dns: str | None
    verified_token: str | None

    @property
    def changes(self) -> tuple[Row, ...]:
        return tuple(row for row in self.rows if row.action != "keep")


def _validate_funnel_host(_context: click.Context, _param: click.Parameter, value: str | None) -> str | None:
    if value is None:
        return None
    host = value.strip().rstrip(".").lower()
    if not _HOST_RE.match(host):
        raise click.BadParameter(f"expected a DNS name like machine.tailnet.ts.net, got {value!r}")
    return host


@click.command(name="tasks:setup", help="Configure your env files so local Tasks runs use Modal sandboxes.")
@click.option("--dry-run", is_flag=True, help="Print the plan and change nothing.")
@click.option("--yes", is_flag=True, help="Apply the plan without asking. Required without a terminal.")
@click.option("--force", is_flag=True, help="Allow replacing values you set yourself.")
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Never prompt or open a browser, and exit 1 when manual steps remain.",
)
@click.option("--refresh-token", is_flag=True, help="Mint a new gateway dev token even if the current one is live.")
@click.option(
    "--funnel-host",
    callback=_validate_funnel_host,
    help="Tailscale Funnel host, for when the Funnel runs on another machine such as your laptop.",
)
def tasks_setup(
    dry_run: bool, yes: bool, force: bool, non_interactive: bool, refresh_token: bool, funnel_host: str | None
) -> None:
    root = Path(REPO_ROOT)
    texts = {name: env_file.read(root / name) for name in (ENV, ENV_LOCAL)}
    plan = build_plan(texts, env_file.read(root / ENV_EXAMPLE), os.environ, funnel_host, refresh_token, non_interactive)
    _print_plan(plan)

    remaining = dict(plan.remaining)
    if dry_run:
        _print_remaining(remaining)
        click.echo("[DRY-RUN] Nothing changed.")
        return
    wrote = False
    if not plan.changes:
        click.echo("Nothing to change.")
    else:
        _confirm(plan.changes, interactive=not non_interactive and _terminal(), yes=yes, force=force)
        assign, disable = _edits(plan.changes)
        mint_row = next((row for row in plan.changes if row.key == TOKEN_KEY and row.new is None), None)
        if mint_row is not None:
            token = _mint_token(remaining)
            if token is not None:
                assign[mint_row.file][TOKEN_KEY] = token
        wrote = _apply(root, texts, assign, disable)

    final = {name: env_file.values(env_file.read(root / name)) for name in (ENV, ENV_LOCAL)}
    for topic, step in _checks(final, plan.funnel_dns, plan.verified_token).items():
        remaining.setdefault(topic, step)
    _print_remaining(remaining)
    if wrote:
        click.echo(RESTART_HINT)
    if non_interactive and remaining:
        raise SystemExit(1)


def _terminal() -> bool:
    return sys.stdin.isatty()


def build_plan(
    texts: Mapping[str, str],
    example: str,
    environ: Mapping[str, str],
    funnel_host: str | None,
    refresh_token: bool,
    non_interactive: bool,
) -> Plan:
    parsed = {name: env_file.values(text) for name, text in texts.items()}
    current = {key: _effective(parsed, key) for key in (*MODAL_KEYS, TOKEN_KEY, "SANDBOX_AI_GATEWAY_PRODUCTS")}
    remaining: dict[str, str] = {}

    desired: dict[str, Desired] = {"SANDBOX_PROVIDER": Desired(PROVIDER, "Modal sandboxes, like production")}
    desired.update(_modal_desired(current, remaining))
    desired["SANDBOX_AI_GATEWAY_URL"] = Desired(GATEWAY_URL, "production AI gateway")
    desired["SANDBOX_AI_GATEWAY_PRODUCTS"] = _products_desired(current["SANDBOX_AI_GATEWAY_PRODUCTS"])
    token = _token_desired(current[TOKEN_KEY], refresh_token, non_interactive, remaining)
    if token is not None:
        desired[TOKEN_KEY] = token

    funnel_dns = funnel_host or coder.tailscale_self_dns()
    if funnel_dns is None:
        remaining["funnel"] = FUNNEL_STEP
    else:
        desired["SANDBOX_API_URL"] = Desired(f"https://{funnel_dns}", "Tailscale Funnel on port 443")
        desired["SANDBOX_MCP_URL"] = Desired(f"https://{funnel_dns}:10000/mcp", "Tailscale Funnel on port 10000")

    example_values = env_file.values(example)
    rows = [_row(parsed, key, want, example_values.get(key, [])) for key, want in desired.items()]
    unsafe = [row for row in rows if row.new is not None and not env_file.is_safe_value(row.new)]
    for row in unsafe:
        remaining[f"unsafe:{row.key}"] = (
            f"Set {row.key} in {row.file} by hand: it holds characters hogli does not write unquoted."
        )
    rows = [row for row in rows if row not in unsafe]
    rows.extend(_disable_rows(parsed))
    remaining.update(_shell_overrides(parsed, environ, desired))
    verified_token = token.value if token is not None and "token" not in remaining else None
    return Plan(rows=tuple(rows), remaining=remaining, funnel_dns=funnel_dns, verified_token=verified_token)


def _effective(parsed: Mapping[str, Mapping[str, list[str]]], key: str) -> str | None:
    if key in parsed[ENV]:
        return parsed[ENV][key][-1]
    if key in parsed[ENV_LOCAL]:
        return parsed[ENV_LOCAL][key][0]
    return None


def _row(parsed: Mapping[str, Mapping[str, list[str]]], key: str, want: Desired, defaults: list[str]) -> Row:
    file = ENV if key in parsed[ENV] else ENV_LOCAL
    current = _effective(parsed, key)
    if current is None:
        return Row(key, file, None, want.value, "add", want.reason)
    if current == want.value:
        return Row(key, file, current, want.value, "keep", want.reason)
    needs_force = bool(current) and not want.overwrite_ok and current not in defaults
    return Row(key, file, current, want.value, "update", want.reason, needs_force)


def _shell_overrides(
    parsed: Mapping[str, Mapping[str, list[str]]], environ: Mapping[str, str], desired: Mapping[str, Desired]
) -> dict[str, str]:
    exported = {key: value for key, value in environ.items() if _effective(parsed, key) is None}
    stale = [key for key, want in desired.items() if key in exported and exported[key] != want.value]
    stale += [key for key in LEGACY_KEYS if key in exported and _disable_reason(key, exported[key])]
    return {
        f"shell:{key}": (
            f"{key} is exported in this shell but no env file sets it: re-activate flox, "
            "or unset it in your shell profile if it is set there."
        )
        for key in stale
    }


def _disable_rows(parsed: Mapping[str, Mapping[str, list[str]]]) -> list[Row]:
    rows: list[Row] = []
    for file in (ENV, ENV_LOCAL):
        for key in LEGACY_KEYS:
            if key not in parsed[file]:
                continue
            value = parsed[file][key][-1]
            reason = _disable_reason(key, value)
            if reason is not None:
                rows.append(Row(key, file, value, None, "disable", reason))
    return rows


def _disable_reason(key: str, value: str) -> str | None:
    if key == "SANDBOX_LLM_GATEWAY_URL":
        return "the legacy LLM gateway is retired for local runs"
    assert key == "SANDBOX_AI_GATEWAY_WORKER_URL"
    if any(host in value for host in LOCAL_HOSTS):
        return "points at a local gateway"
    return None


def _modal_desired(current: Mapping[str, str | None], remaining: dict[str, str]) -> dict[str, Desired]:
    if all(current[key] for key in MODAL_KEYS):
        return {key: Desired(current[key], "shared Modal dev token") for key in MODAL_KEYS}
    tokens = _op_read_modal()
    if tokens is None:
        remaining["modal"] = MODAL_STEP
        return {}
    return {key: Desired(tokens[key], "shared Modal dev token from 1Password") for key in MODAL_KEYS}


def _op_read_modal() -> dict[str, str] | None:
    op = shutil.which("op")
    if op is None:
        return None
    tokens: dict[str, str] = {}
    for key in MODAL_KEYS:
        try:
            completed = subprocess.run(
                [op, "read", f"{OP_ITEM}/{key}"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=OP_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = completed.stdout.strip()
        if completed.returncode != 0 or not value:
            return None
        if not env_file.is_safe_value(value):
            raise click.ClickException(f"1Password returned a {key} that cannot be written to an env file safely.")
        tokens[key] = value
    return tokens


def _products_desired(current: str | None) -> Desired:
    entries = [entry.strip() for entry in (current or "").split(",") if entry.strip()]
    if GATEWAY_PRODUCT in entries:
        return Desired(current, f"routes {GATEWAY_PRODUCT} to the gateway")
    reason = f"adds {GATEWAY_PRODUCT}, keeping the existing entries" if entries else f"routes {GATEWAY_PRODUCT}"
    return Desired(",".join([*entries, GATEWAY_PRODUCT]), reason, overwrite_ok=True)


def _token_desired(
    current: str | None, refresh_token: bool, non_interactive: bool, remaining: dict[str, str]
) -> Desired | None:
    problem = _token_refresh_reason(current, refresh_token)
    if problem is None:
        return Desired(current, "dev token is live for more than a day")
    if non_interactive:
        remaining["token"] = _token_step(problem)
        return Desired(current, f"needs a new dev token: {problem}") if current is not None else None
    replaceable = not current or current.startswith("phe_")
    return Desired(None, f"new 7-day dev token after browser approval: {problem}", overwrite_ok=replaceable)


def _token_refresh_reason(current: str | None, refresh_token: bool) -> str | None:
    if refresh_token:
        return "--refresh-token was passed"
    if not current:
        return "there is no dev token yet"
    return _token_problem(current)


def _token_problem(token: str) -> str | None:
    if not token.startswith("phe_"):
        return "the current value is not a phe_ token"
    try:
        status = gateway.token_status(posthog_auth.DEFAULT_HOST, token)
    except click.ClickException as error:
        return f"could not check the current one: {error.message}"
    if status.get("status") != "live":
        return f"the current one is {status.get('status')}"
    try:
        expires_at = datetime.fromisoformat(str(status["expires_at"]))
    except (KeyError, ValueError):
        return "the gateway did not say when the current one expires"
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at - datetime.now(UTC) < TOKEN_REFRESH_WINDOW:
        return "the current one expires within a day"
    return None


def _print_plan(plan: Plan) -> None:
    click.echo("Plan for local Tasks runs on Modal:")
    for row in plan.rows:
        values = _show(row.key, row.current, "unset")
        if row.action != "keep":
            values = f"{values} -> {_show(row.key, row.new, _placeholder(row))}"
        force = "  [needs --force]" if row.needs_force else ""
        click.echo(f"  {row.action:<8} {row.key:<30} {row.file:<11} {values}  ({row.reason}){force}")


def _placeholder(row: Row) -> str:
    return "commented out" if row.action == "disable" else "new token"


def _show(key: str, value: str | None, missing: str) -> str:
    if value is None:
        return f"({missing})"
    if value == "":
        return "(empty)"
    if key not in SECRET_KEYS:
        return value
    if len(value) <= 12:
        return "…"
    prefix = value[: value.index("_") + 1] if "_" in value[:5] else ""
    return f"{prefix}…{value[-4:]}"


def _confirm(changes: tuple[Row, ...], *, interactive: bool, yes: bool, force: bool) -> None:
    overwrites = ", ".join(f"{row.key} in {row.file}" for row in changes if row.needs_force)
    blocked = bool(overwrites) and not force
    if yes and not blocked:
        return
    if not interactive:
        if not yes:
            raise click.UsageError("There is no terminal to confirm in. Re-run with --yes to apply this plan.")
        raise click.UsageError(
            f"This would replace values you set yourself ({overwrites}). Re-run with --force to replace them."
        )
    prompt = (
        f"Apply these changes, replacing your own values for {overwrites}?" if overwrites else "Apply these changes?"
    )
    if not click.confirm(prompt, default=False):
        raise click.ClickException("Aborted. Nothing changed.")


def _edits(changes: tuple[Row, ...]) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    assign: dict[str, dict[str, str]] = {ENV: {}, ENV_LOCAL: {}}
    disable: dict[str, set[str]] = {ENV: set(), ENV_LOCAL: set()}
    for row in changes:
        if row.action == "disable":
            disable[row.file].add(row.key)
        elif row.new is not None:
            assign[row.file][row.key] = row.new
    return assign, disable


def _mint_token(remaining: dict[str, str]) -> str | None:
    click.echo("Approve the gateway dev token in your browser.")
    try:
        minted = gateway.mint_token(posthog_auth.DEFAULT_HOST, cap_usd=None, ttl_seconds=TOKEN_TTL_SECONDS)
    except (posthog_auth.AuthError, click.ClickException) as error:
        remaining["token"] = _token_step(error.message)
        return None
    token = str(minted["token"])
    if not token.startswith("phe_") or not env_file.is_safe_value(token):
        raise click.ClickException("The gateway returned a token hogli cannot write safely.")
    return token


def _apply(
    root: Path, texts: Mapping[str, str], assign: Mapping[str, dict[str, str]], disable: Mapping[str, set[str]]
) -> bool:
    updates = {
        name: env_file.edit(
            texts[name], assign=assign[name], disable=disable[name], disable_marker=DISABLE_MARKER, header=HEADER
        )
        for name in (ENV, ENV_LOCAL)
        if assign[name] or disable[name]
    }
    stamp = _today()
    for name, updated in updates.items():
        path = root / name
        backup = root / f"{name}.bak-tasks-setup-{stamp}"
        if path.exists() and not backup.exists():
            shutil.copy2(path, backup)
            click.echo(f"Backed up {name} to {backup.name}.")
        env_file.write(path, updated)
        click.echo(f"Updated {name}.")

        written = env_file.values(env_file.read(path))
        for key, value in assign[name].items():
            assert key in written
            assert all(entry == value for entry in written[key])
        for key in disable[name]:
            assert key not in written
    return bool(updates)


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _token_step(problem: str) -> str:
    return (
        f"Mint a gateway dev token ({problem}): run `hogli tasks:setup --refresh-token` in a terminal "
        "and approve it in your browser."
    )


def _checks(
    final: Mapping[str, Mapping[str, list[str]]], funnel_dns: str | None, verified_token: str | None
) -> dict[str, str]:
    click.echo("Checks:")
    failed: dict[str, str] = {}
    modal_ok = all(_effective(final, key) for key in MODAL_KEYS)
    _report(modal_ok, "Modal token present")
    if not modal_ok:
        failed["modal"] = MODAL_STEP

    token = _effective(final, TOKEN_KEY)
    token_problem = None if token is not None and token == verified_token else _token_refresh_reason(token, False)
    _report(token_problem is None, "gateway dev token live" + (f" ({token_problem})" if token_problem else ""))
    if token_problem is not None:
        failed["token"] = _token_step(token_problem)

    _report(funnel_dns is not None, f"Tailscale Funnel host: {funnel_dns}" if funnel_dns else "Tailscale available")
    if funnel_dns is None:
        failed["funnel"] = FUNNEL_STEP
    return failed


def _report(ok: bool, label: str) -> None:
    click.echo(f"  {'✓' if ok else '✗'} {label}")


def _print_remaining(remaining: Mapping[str, str]) -> None:
    if not remaining:
        return
    click.echo("Remaining manual steps:")
    for step in remaining.values():
        click.echo(f"  - {step}")
