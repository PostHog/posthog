"""CI insights for the current repo + branch.

A vendor-neutral adapter over a CI-insights backend. Every backend-specific
detail lives in one place (``MendralBackend``); swapping providers means
replacing that class, leaving the call sites and the debugging-ci-failures
skill untouched.

    hogli ci:insights                      # digest for the current repo + branch
    hogli ci:insights search "<error>"     # match insights to a failure string
    hogli ci:insights view <id> [--json]   # one insight + its remediation actions
    hogli ci:insights plan <id>            # print the recommended remediation plan

When stdout is not a terminal the backend emits JSON on its own, so piped/agent
callers get structured output without a flag; ``--json`` forces it in a tty.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import click

# Actionable statuses, most-preferred first — picks which remediation plan to
# surface when an insight carries several recommended actions.
_ACTIONABLE_STATUSES: tuple[str, ...] = ("proposed", "in_progress", "in_review")


def _run(*args: str) -> int:
    """Run the backend CLI inheriting stdio; return its exit code."""
    return subprocess.run(args).returncode


def _capture(*args: str) -> str:
    """Run the backend CLI capturing stdout; raise ClickException on failure."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException((result.stderr or result.stdout).strip() or "backend command failed")
    return result.stdout


class MendralBackend:
    """The only Mendral-aware code. Swap this class to change providers."""

    name = "Mendral"
    binary = "mendral"
    install_hint = "brew install mendral-ai/tap/mendral"

    def ensure_ready(self) -> None:
        if shutil.which(self.binary) is None:
            raise click.ClickException(
                f"{self.name} CLI not found. Install it with:\n"
                f"    {self.install_hint}\n"
                f"Then authenticate:  ! {self.binary} auth login"
            )
        # `mendral auth status` exits 0 whether or not you are logged in, so the
        # exit code carries no signal — read the message instead.
        if "Not authenticated" in _capture(self.binary, "auth", "status"):
            raise click.ClickException(f"{self.name} is not authenticated. Run:  ! {self.binary} auth login")

    def digest(self) -> int:
        return _run(self.binary, "here")

    def search(self, query: str, *, as_json: bool) -> int:
        return _run(self.binary, "insight", "search", query, *(["--json"] if as_json else []))

    def view(self, insight_id: str, *, as_json: bool) -> int:
        return _run(self.binary, "insight", "view", insight_id, *(["--json"] if as_json else []))

    def plan(self, insight_id: str) -> int:
        raw = _capture(self.binary, "insight", "view", insight_id, "--json")
        try:
            insight = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Could not parse the {self.name} response for {insight_id}: {exc}")
        actions = [action for action in (insight.get("actions") or []) if isinstance(action, dict)]
        action = _recommended_action(actions)
        if action is None:
            raise click.ClickException(f"No remediation plan available for {insight_id}.")
        click.secho(f"{action.get('title') or 'Remediation plan'}  [{action.get('status')}]", bold=True)
        if action.get("status") == "merged":
            click.secho("A fix for this insight has already been merged.", fg="yellow")
        full_plan = action.get("full_plan")
        if not full_plan:
            raise click.ClickException("The recommended action has no plan text.")
        click.echo(full_plan)
        return 0


def _recommended_action(actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the plan worth showing: a recommended, still-actionable action if one
    exists; else any recommended action; else the first action."""
    recommended = [action for action in actions if action.get("recommended")]
    for status in _ACTIONABLE_STATUSES:
        for action in recommended:
            if action.get("status") == status:
                return action
    if recommended:
        return recommended[0]
    return actions[0] if actions else None


_BACKEND: MendralBackend = MendralBackend()


# Each entry point calls ensure_ready() in its own body rather than the group
# callback, so `--help` (which short-circuits before the body) works without the
# backend installed. SystemExit is used throughout — the telemetry wrapper
# records its code, unlike click's ctx.exit().
@click.group(name="ci:insights", invoke_without_command=True, help="Show CI insights for the current repo + branch.")
@click.pass_context
def ci_insights(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        _BACKEND.ensure_ready()
        raise SystemExit(_BACKEND.digest())


@ci_insights.command(name="search", help="Search CI insights by keyword or error string.")
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON instead of a table.")
def search(query: str, as_json: bool) -> None:
    _BACKEND.ensure_ready()
    raise SystemExit(_BACKEND.search(query, as_json=as_json))


@ci_insights.command(name="view", help="View a CI insight and its remediation actions.")
@click.argument("insight_id")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON instead of a table.")
def view(insight_id: str, as_json: bool) -> None:
    _BACKEND.ensure_ready()
    raise SystemExit(_BACKEND.view(insight_id, as_json=as_json))


@ci_insights.command(name="plan", help="Print the recommended remediation plan (does not apply changes).")
@click.argument("insight_id")
def plan(insight_id: str) -> None:
    _BACKEND.ensure_ready()
    raise SystemExit(_BACKEND.plan(insight_id))
