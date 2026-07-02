"""hogli devex:feedback — send feedback about the dev experience to the devex team.

Feedback lands as a ``hogli_feedback`` event in PostHog's internal hogli project,
carrying the same environment context that hogli telemetry attaches (environment,
agent, git branch, repo vintage) so the devex team can triage it.

Unlike passive telemetry, feedback is an explicit, user-initiated action: the
command name states exactly what it does, so it is sent even when passive
telemetry is opted out — though it then uses a throwaway distinct id rather than
minting a persistent one. It still needs a configured telemetry API key as a
destination.
"""

from __future__ import annotations

import os
import sys
import uuid
import select
import platform
from datetime import UTC, datetime
from typing import Any

import click
import requests
from hogli import telemetry
from hogli.hooks import telemetry_property_hooks
from hogli.manifest import get_manifest

_EVENT = "hogli_feedback"
_DEFAULT_HOST = "https://us.i.posthog.com"
_CATEGORIES = ("bug", "idea", "praise", "question", "other")


def _endpoint() -> tuple[str, str]:
    """(host, api_key) for the feedback event, env override then manifest config."""
    cfg = get_manifest().config.get("telemetry", {}) or {}
    host = os.environ.get("POSTHOG_TELEMETRY_HOST") or cfg.get("host", _DEFAULT_HOST)
    api_key = os.environ.get("POSTHOG_TELEMETRY_API_KEY") or cfg.get("api_key", "")
    return host, api_key


def _distinct_id() -> str:
    """Distinct id for the feedback event.

    Reuse the persisted anonymous telemetry id when telemetry is enabled, so
    feedback correlates with the sender's other hogli events. Under opt-out
    (DO_NOT_TRACK, POSTHOG_TELEMETRY_OPT_OUT, disabled config, CI), don't mint or
    persist a durable id just to send an explicit one-off — use a throwaway.
    """
    if telemetry.is_enabled():
        return telemetry.get_anonymous_id()
    return str(uuid.uuid4())


def _stdin_is_tty() -> bool:
    """True when stdin is an interactive terminal — False, not a crash, when stdin
    is closed or absent (daemon / sandbox / agent contexts)."""
    try:
        return sys.stdin.isatty()
    except (ValueError, AttributeError):
        return False


def _stdin_has_data() -> bool:
    """True when piped stdin already has bytes ready, so reading won't block.

    Guards ``echo … | hogli devex:feedback`` while keeping a held-open empty pipe
    (an agent that spawned the command with an unwritten stdin) from hanging it.
    """
    try:
        return bool(select.select([sys.stdin], [], [], 0)[0])
    except Exception:
        return False


def _context_properties() -> dict[str, Any]:
    """Environment context attached to the feedback event.

    Reuses the registered telemetry property hooks (environment, agent,
    git_branch, repo_sha, …) so feedback carries the same triage context as
    hogli's regular events, plus a few static platform props.
    """
    props: dict[str, Any] = {
        "os": platform.system(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
    }
    for hook in telemetry_property_hooks:
        try:
            props.update(hook("devex:feedback"))
        except Exception:
            pass
    return props


def _send(message: str, category: str | None, context: dict[str, Any]) -> tuple[bool, str]:
    """POST the feedback event synchronously. Returns (ok, error_message)."""
    host, api_key = _endpoint()
    if not api_key:
        return False, "no telemetry API key configured, so there is nowhere to send feedback"

    # context first, then the command's invariants, so no context key can override
    # the anonymity flag or the message.
    props: dict[str, Any] = {**context, "$process_person_profile": False, "message": message}
    if category:
        props["category"] = category

    entry = {
        "event": _EVENT,
        "distinct_id": _distinct_id(),
        "properties": props,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        resp = requests.post(f"{host}/batch/", json={"api_key": api_key, "batch": [entry]}, timeout=10)
        resp.raise_for_status()
        return True, ""
    except Exception as exc:
        return False, str(exc)


@click.command(name="devex:feedback")
@click.argument("message", nargs=-1)
@click.option("-c", "--category", type=click.Choice(_CATEGORIES), help="Optional feedback category.")
@click.option("-y", "--yes", is_flag=True, help="Send without the confirmation preview (implied when non-interactive).")
def devex_feedback(message: tuple[str, ...], category: str | None, yes: bool) -> None:
    """Send feedback about the dev experience to the PostHog devex team.

    Humans and agents alike: when a hogli command, the dev stack, or any repo
    tooling is slow, broken, confusing, or delightful, say so here. It lands as
    a `hogli_feedback` event the devex team triages, tagged with your
    environment, branch, and whether an agent sent it.

    \b
        hogli devex:feedback "dev:reset took 20 min and the schema restore silently failed"
        hogli devex:feedback -c idea "add a hogli db:snapshot to save/restore local state"
        echo "long note" | hogli devex:feedback

    The message is the only free-form content sent; everything else is the same
    environment context hogli telemetry already attaches. Run interactively to
    confirm before sending.
    """
    interactive = _stdin_is_tty()
    text = " ".join(message).strip()

    # No inline message: prompt an interactive human, or read piped stdin — but only
    # when data is actually waiting, so a held-open empty pipe can't block forever.
    if not text and interactive:
        text = click.prompt("Your feedback for the devex team", default="", show_default=False).strip()
    elif not text and _stdin_has_data():
        text = sys.stdin.read().strip()

    if not text:
        raise click.ClickException('nothing to send — provide a message: hogli devex:feedback "..."')

    # Preview + confirm for interactive humans; agents and pipes send straight through.
    if interactive and not yes:
        click.echo()
        click.secho("Sending to the devex team:", bold=True)
        click.echo(f"  {text}")
        if category:
            click.echo(f"  category: {category}")
        click.secho(
            "\nTagged with the same environment context hogli telemetry attaches (environment, agent, branch, repo).\n",
            dim=True,
        )
        if not click.confirm("Send?", default=True):
            click.secho("Not sent.", fg="yellow")
            return

    # Collect context only once we're committed to sending — the telemetry hooks can
    # shell out (gh api) and persist cache, so a declined preview stays side-effect-free.
    context = _context_properties()

    ok, err = _send(text, category, context)
    if ok:
        click.secho("✓ Sent to the devex team. Thank you!", fg="green")
        return

    click.secho(f"✗ Could not send feedback: {err}", fg="red", err=True)
    click.echo("Check your connection and retry, or share it with the devex team directly.", err=True)
    raise SystemExit(1)
