from __future__ import annotations

import os
import subprocess

import click

from hogli_commands import ci_insights

_SETUP_HINT = (
    "Agent token usage reaches PostHog only from agents that send $ai_generation events with $ai_git_branch. "
    "For Claude Code, set up the PostHog plugin's LLM analytics ingestion (/posthog:llma-cc-setup)."
)


def _gh_login() -> str | None:
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=10.0, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    login = result.stdout.strip()
    return login if result.returncode == 0 and login else None


def _format_tokens(value: float) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if value >= size:
            return f"{value / size:.1f}{unit}"
    return f"{value:.0f}"


def _render(
    spend: ci_insights._AuthorLLMSpendList, coverage: ci_insights._LLMSpendCoverage, *, author: str, days: int
) -> None:
    rows = [item for item in spend["items"] if item["llm_spend"] is not None]
    if not rows:
        click.echo(f"No agent LLM spend is attributed to {author}'s pull requests in the last {days} days.")
        click.echo(_SETUP_HINT)
        return
    rows.sort(key=lambda item: item["llm_spend"]["cost_usd"] if item["llm_spend"] else 0.0, reverse=True)
    headers = ("cost", "generations", "input", "cache write", "cache read", "output", "peak ctx")
    cells = [
        (
            f"${usage['cost_usd']:.2f}",
            str(usage["generations"]),
            _format_tokens(usage["input_tokens"]),
            _format_tokens(usage["cache_creation_input_tokens"]),
            _format_tokens(usage["cache_read_input_tokens"]),
            _format_tokens(usage["output_tokens"]),
            _format_tokens(usage["peak_context_tokens"]),
        )
        for item in rows
        if (usage := item["llm_spend"]) is not None
    ]
    widths = [max(len(header), *(len(row[index]) for row in cells)) for index, header in enumerate(headers)]
    click.echo("  ".join(header.rjust(width) for header, width in zip(headers, widths)) + "  pull request")
    for item, row in zip(rows, cells):
        label = ci_insights._terminal_text(f"#{item['number']} {item['title']}")[:70]
        click.echo("  ".join(cell.rjust(width) for cell, width in zip(row, widths)) + "  " + label)

    total = sum(item["llm_spend"]["cost_usd"] for item in rows if item["llm_spend"])
    listed = f"{len(spend['items'])}+" if spend["truncated"] else str(len(spend["items"]))
    click.echo(f"\n${total:.2f} across {len(rows)} of {listed} pull requests active in the last {days} days.")
    if coverage["cost_usd"] > 0:
        click.echo(
            f"Repo coverage: {coverage['attributed_cost_usd'] / coverage['cost_usd']:.0%} of "
            f"${coverage['cost_usd']:.2f} repo-stamped agent spend maps to a pull request."
        )


@click.command(name="agent:usage")
@click.option("--author", help="GitHub handle whose pull requests to show. Defaults to your gh login.")
@click.option(
    "--days", type=click.IntRange(min=1, max=366), default=30, show_default=True, help="Look back this many days."
)
@click.option(
    "--limit", type=click.IntRange(min=1, max=200), default=100, show_default=True, help="Pull requests to read."
)
@click.option("--repo", help="'owner/name' to read; defaults to the origin remote.")
@click.option(
    "--project",
    default=lambda: os.environ.get("POSTHOG_CI_INSIGHTS_PROJECT_ID") or ci_insights._DEFAULT_PROJECT_ID,
    help="PostHog project id holding the GitHub source.",
)
@click.option(
    "--host",
    default=lambda: os.environ.get("POSTHOG_CI_INSIGHTS_HOST") or ci_insights._DEFAULT_HOST,
    help="PostHog host to read from.",
)
@click.option(
    "--timeout",
    type=click.FloatRange(min=0, min_open=True),
    default=60.0,
    show_default=True,
    help="Per-request timeout in seconds.",
)
@click.option("--json", "as_json", is_flag=True, help="Shorthand for --format json.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["auto", "text", "json"]),
    default="auto",
    show_default=True,
    help="'auto' emits JSON when stdout is not a terminal.",
)
def cmd_agent_usage(
    author: str | None,
    days: int,
    limit: int,
    repo: str | None,
    project: str,
    host: str,
    timeout: float,
    as_json: bool,
    output_format: str,
) -> None:
    """Show agent LLM token spend per pull request, from engineering analytics.

    Spend is attributed to a pull request by the git branch and AI session on each
    $ai_generation event, the same rule as the pull request page. Repo coverage is the
    share of agent spend stamped with this repo that maps to any pull request.
    """
    options = ci_insights._Options(
        repo=repo,
        project=project,
        host=host,
        timeout=timeout,
        output_format="json" if as_json else output_format,
        limit=limit,
    )
    try:
        login = author or _gh_login()
        if not login:
            raise ci_insights._ApiError("Could not read your GitHub login from gh. Pass --author.")
        api = ci_insights._resolve_source(options.api(), repo)
        spend = api.author_llm_spend(author=login, days=days, limit=limit)
        coverage = api.llm_spend_coverage(days=days)
    except ci_insights._ApiError as error:
        ci_insights._fail(error)

    if options.emits_json():
        ci_insights._emit_json(
            {"author": login, "repo": api.repo, "days": days, "pull_requests": spend, "repo_coverage": coverage}
        )
    _render(spend, coverage, author=login, days=days)
