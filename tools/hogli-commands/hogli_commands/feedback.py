"""hogli devex:feedback — send feedback about the dev experience to the devex team.

Feedback lands as a ``hogli_feedback`` event in PostHog's internal hogli project,
carrying the same environment context that hogli telemetry attaches (environment,
agent, git branch, repo vintage) so the devex team can triage it.

Unlike passive telemetry, feedback is an explicit, user-initiated action: the
command name states exactly what it does, so it is sent even when passive
telemetry is opted out. It still needs a configured telemetry API key as a
destination, and it always prints exactly what it sends.
"""

from __future__ import annotations

import os
import sys
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

# Context keys surfaced in the interactive preview so a human sees exactly what
# rides along with their message before confirming the send.
_PREVIEW_KEYS = ("environment", "agent", "is_agent", "git_branch", "repo_sha", "in_flox", "os")


def _endpoint() -> tuple[str, str]:
    """(host, api_key) for the feedback event, env override then manifest config."""
    cfg = get_manifest().config.get("telemetry", {}) or {}
    host = os.environ.get("POSTHOG_TELEMETRY_HOST") or cfg.get("host", _DEFAULT_HOST)
    api_key = os.environ.get("POSTHOG_TELEMETRY_API_KEY") or cfg.get("api_key", "")
    return host, api_key


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

    props: dict[str, Any] = {"$process_person_profile": False, "message": message, **context}
    if category:
        props["category"] = category

    entry = {
        "event": _EVENT,
        "distinct_id": telemetry.get_anonymous_id(),
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

    The message text is the only free-form content sent; run it interactively to
    preview the attached context before confirming.
    """
    interactive = sys.stdin.isatty()
    text = " ".join(message).strip()

    # No inline message: read piped stdin, or prompt an interactive human.
    if not text and not interactive:
        text = sys.stdin.read().strip()
    elif not text and interactive:
        text = click.prompt("Your feedback for the devex team", default="", show_default=False).strip()

    if not text:
        raise click.ClickException('nothing to send — provide a message: hogli devex:feedback "..."')

    context = _context_properties()

    # Preview + confirm for interactive humans; agents and pipes send straight through.
    if interactive and not yes:
        click.echo()
        click.secho("Sending to the devex team:", bold=True)
        click.echo(f"  {text}")
        if category:
            click.echo(f"  category: {category}")
        click.echo()
        click.secho("Attached context (no free-form text beyond your message):", dim=True)
        for key in _PREVIEW_KEYS:
            if key in context:
                click.echo(f"  {key}: {context[key]}")
        click.echo()
        if not click.confirm("Send?", default=True):
            click.secho("Not sent.", fg="yellow")
            return

    ok, err = _send(text, category, context)
    if ok:
        click.secho("✓ Sent to the devex team. Thank you!", fg="green")
        return

    click.secho(f"✗ Could not send feedback: {err}", fg="red", err=True)
    click.echo("Check your connection and retry, or share it with the devex team directly.", err=True)
    raise SystemExit(1)
