"""CI insights for the current repo + branch, read from PostHog's engineering analytics.

    hogli ci:insights                       # digest for the current repo + branch
    hogli ci:insights search "<error>"      # match a failure by test name or error text
    hogli ci:insights view <ref> [--logs]   # one failure, with its failing log lines

An ordinary REST client over the named ``engineering_analytics`` endpoints — the same ones
the in-app UI and the MCP tools read, so there is no second copy of the domain rules here.
This module only picks endpoints, summarizes, and renders.

Auth reuses the personal API key engineers already mint for the PostHog MCP: its
``mcp_server`` preset grants ``engineering_analytics:write``, which satisfies the ``:read``
these endpoints require. ``POSTHOG_PERSONAL_API_KEY`` (the name the wizard and the rest of
the ecosystem use) is checked first, then ``POSTHOG_AUTH_HEADER`` (the name
``services/mcp`` has you export for mcp-remote). Either can be a literal line in
``.env.local``, which hogli loads on every invocation.

Missing or rejected credentials exit ``78`` (sysexits ``EX_CONFIG``) so the
debugging-ci-failures skill can branch to its read-only ``gh`` fallback on the exit code
rather than on message text. Diagnostics go to stderr, keeping stdout parseable.

When stdout is not a terminal the output is JSON, so piped/agent callers get structure
without a flag; ``--json`` forces it in a tty. That JSON is this command's own summarized
shape, never an endpoint passthrough — ``broken_tests`` alone returns 200 rows whose bytes
are mostly hourly sparklines, which is not something to dump into a transcript.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import hashlib
import subprocess
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn

import click
import requests
from click.core import ParameterSource

_DEFAULT_HOST = "https://us.posthog.com"
# The project holding the synced PostHog/posthog GitHub source. A project id, not a secret
# — committed for the same reason hogli.yaml commits the telemetry write key.
_DEFAULT_PROJECT_ID = "2"

_KEY_ENV_VARS = ("POSTHOG_PERSONAL_API_KEY", "POSTHOG_AUTH_HEADER")
_KEY_MINT_URL = "https://us.posthog.com/settings/user-api-keys?preset=mcp_server"

# sysexits.h EX_CONFIG. Distinct from 1 so a caller can tell "you have not set this up"
# from "the data says something is wrong" without parsing prose.
_EXIT_NOT_CONFIGURED = 78

_DIGEST_ROWS = 8
_SEARCH_ROWS = 10
_SEARCH_DEFAULT_DAYS = 7
_FLAKY_SCAN_LIMIT = 200
# Below this, a ref prefix matches too much to be a useful handle.
_MIN_REF_PREFIX = 4

# BrokenTestState, most urgent first. The endpoint already returns rows in this order, so
# this drives the count summary only — never a client-side re-sort of the rows, which would
# put the classifier's judgement in a second place.
_STATE_MEANINGS: dict[str, str] = {
    "breaking_master": "failing on the default branch, and that job's latest run is still red",
    "blocking_merge_queue": "failing only on merge-queue gate branches — holding up landings on a commit the PR's own CI passed",
    "novel_burst": "first seen within a day and already spreading across branches, not on trunk yet",
    "potentially_resolved": "hit the default branch but that job is green again",
    "flaky": "sporadic across two or more branches over more than a day",
    "pr_only": "confined to one branch — one PR's own problem",
}

_SPARK_LEVELS = " ▁▂▃▄▅▆▇█"

# Digest section keys are also the JSON payload's keys, so the reader-facing headings live
# here rather than being derived from them.
_SECTION_LABELS = {
    "master": "default branch",
    "broken": "broken tests",
    "master_failures": "master failures",
    "branch": "your branch",
}

_CAVEATS = (
    "Fingerprints are pytest-only, so jest/playwright/cargo breakage shows up under master failures, not above.\n"
    "Counts are absolute, never rates — passing runs are not in this data.\n"
    "A run's conclusion can lag until GitHub's webhook settles it; confirm a specific run with `gh`."
)


class _ApiError(Exception):
    """A read that failed, already phrased as something the reader can act on."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def _fail(error: _ApiError) -> NoReturn:
    """Report a failed read on stderr and exit with its code."""
    click.secho(error.message, fg="red", err=True)
    raise SystemExit(error.exit_code)


def _token() -> str:
    """The personal API key, from the first env var that carries one.

    ``POSTHOG_AUTH_HEADER`` holds a whole ``Bearer <key>`` header value, so strip the
    scheme rather than sending it twice.
    """
    for var in _KEY_ENV_VARS:
        raw = (os.environ.get(var) or "").strip()
        if raw:
            return raw.removeprefix("Bearer ")
    raise _ApiError(
        "CI insights needs a PostHog personal API key.\n"
        f"  Mint one — or reuse the key you already made for the PostHog MCP: {_KEY_MINT_URL}\n"
        f"  Then set {_KEY_ENV_VARS[0]} in your shell, or add it as a literal line in .env.local.\n"
        "  Until then, fall back to read-only `gh` inspection.",
        exit_code=_EXIT_NOT_CONFIGURED,
    )


def _request(url: str, *, token: str, params: dict[str, Any], timeout: float) -> requests.Response:
    """One authenticated GET. The single HTTP seam, so tests can replace it wholesale."""
    return requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params,
        timeout=timeout,
    )


def _parse(response: requests.Response, action: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise _ApiError(f"{action} returned a non-JSON body: {exc}") from exc


def _detail(response: requests.Response) -> str:
    """The API's own explanation, which is user-safe on every status mapped below."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(body, dict):
        return str(body.get("detail") or body)[:400]
    return str(body)[:400]


def _explain(response: requests.Response, action: str, *, host: str, project_id: str) -> _ApiError:
    """Turn an HTTP failure into the next thing the reader should do about it."""
    detail = _detail(response)
    status = response.status_code
    if status == 401:
        return _ApiError(
            f"{host} rejected the API key. It may be revoked, or minted in a different region.",
            exit_code=_EXIT_NOT_CONFIGURED,
        )
    if status == 403 and "scope" in detail:
        return _ApiError(
            "The API key lacks 'engineering_analytics:read'.\n"
            f"  Re-mint it with the MCP Server preset, which covers it: {_KEY_MINT_URL}",
            exit_code=_EXIT_NOT_CONFIGURED,
        )
    if status == 403:
        return _ApiError(
            f"{detail}\n  Engineering analytics is flag-gated — ask #team-devex to enable it for your account.",
            exit_code=_EXIT_NOT_CONFIGURED,
        )
    if status == 400 and "source" in detail:
        return _ApiError(
            f"{detail}\n  No GitHub source readable in project {project_id} — check the project id, and that "
            "your user has warehouse access to the source."
        )
    if status == 404:
        return _ApiError(f"No {action} endpoint at {host} for project {project_id} — the project id may be wrong.")
    return _ApiError(f"{action} failed ({status}): {detail}")


@dataclass(frozen=True, kw_only=True)
class _Api:
    """A reader bound to one project, and after ``bound()`` to one repository."""

    host: str
    project_id: str
    token: str
    timeout: float
    source_id: str | None = None
    repo: str | None = None

    def bound(self, *, source_id: str, repo: str) -> _Api:
        """A copy that scopes every later read to one source and repository."""
        return _Api(
            host=self.host,
            project_id=self.project_id,
            token=self.token,
            timeout=self.timeout,
            source_id=source_id,
            repo=repo,
        )

    def get(self, action: str, **params: Any) -> Any:
        url = f"{self.host}/api/projects/{self.project_id}/engineering_analytics/{action}/"
        query = {"source_id": self.source_id, "repo": self.repo, **params}
        try:
            response = _request(
                url,
                token=self.token,
                params={key: value for key, value in query.items() if value},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise _ApiError(f"Could not reach {self.host}: {exc}") from exc
        if response.status_code == 200:
            return _parse(response, action)
        raise _explain(response, action, host=self.host, project_id=self.project_id)


def _git(*args: str) -> str | None:
    """Trimmed stdout of a git command, None on any failure."""
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5.0)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _origin_repo() -> str | None:
    """'owner/name' from the origin remote, for either URL form GitHub hands out."""
    url = _git("remote", "get-url", "origin")
    if not url:
        return None
    slug = url.removesuffix("/").removesuffix(".git")
    slug = slug.partition(":")[2] if slug.startswith("git@") else "/".join(slug.split("/")[-2:])
    return slug if slug.count("/") == 1 and all(slug.split("/")) else None


def _current_branch() -> str | None:
    """The checked-out branch, None on a detached HEAD."""
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    return branch if branch and branch != "HEAD" else None


def _resolve_source(api: _Api, repo: str | None) -> _Api:
    """Bind to the synced source for ``repo``, so a fork or unrelated checkout cannot
    silently report another repository's CI as if it were yours."""
    entries = [entry for entry in api.get("sources") if isinstance(entry, dict)]
    wanted = (repo or _origin_repo() or "").lower()
    if not wanted:
        raise _ApiError("Could not read an 'owner/name' repo from the origin remote — pass --repo.")
    for entry in entries:
        if str(entry.get("repo", "")).lower() == wanted and entry.get("synced"):
            return api.bound(source_id=str(entry["id"]), repo=str(entry["repo"]))
    readable = ", ".join(sorted(str(entry.get("repo")) for entry in entries if entry.get("synced"))) or "none"
    raise _ApiError(f"No synced GitHub source for {wanted} in project {api.project_id}. Readable repos: {readable}.")


def _ref(fingerprint: str) -> str:
    """An 8-hex handle for a failure fingerprint, usable as an argv token.

    The fingerprint itself is ``test_id | error_signature`` — spaces and a pipe. Content
    addressing keeps the handle stable across invocations with no cached state, and makes
    it change exactly when the fingerprint does (the recipe is pytest-only v1 and evolves).
    """
    return hashlib.blake2s(fingerprint.encode(), digest_size=4).hexdigest()


def _resolve_ref(rows: list[dict[str, Any]], ref: str) -> dict[str, Any]:
    """Find the one row ``ref`` names, accepting a handle, a handle prefix, a full
    fingerprint, or a test-id substring. Matching several rows is an error, not a guess."""
    lowered = ref.lower()
    candidates = [row for row in rows if _ref(row["fingerprint"]) == lowered or row["fingerprint"] == ref]
    if not candidates and len(ref) >= _MIN_REF_PREFIX:
        candidates = [row for row in rows if _ref(row["fingerprint"]).startswith(lowered)]
    if not candidates:
        candidates = [row for row in rows if lowered in str(row.get("test_id", "")).lower()]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise _ApiError(f"No current failure matches {ref!r}. Refs come from `hogli ci:insights` or `search`.")
    listed = "\n".join(f"  {_ref(row['fingerprint'])}  {row.get('test_id')}" for row in candidates[:_SEARCH_ROWS])
    raise _ApiError(f"{ref!r} matches {len(candidates)} failures:\n{listed}")


def _spark(counts: list[int]) -> str:
    """A one-cell-per-hour histogram, scaled to its own peak.

    An hour with no failures is blank, not the shortest bar — a row of shortest bars would
    read as "it failed a little, constantly".
    """
    peak = max(counts, default=0)
    top = len(_SPARK_LEVELS) - 1
    return "".join(
        _SPARK_LEVELS[0] if not count else _SPARK_LEVELS[min(top, max(1, round(count / peak * top)))]
        for count in counts
    )


def _short(text: str, width: int) -> str:
    return text if len(text) <= width else f"{text[: width - 1]}…"


def _ago(timestamp: str | None) -> str:
    """How long ago an ISO8601 stamp was, at the coarsest unit that still reads usefully."""
    if not timestamp:
        return "-"
    try:
        seen = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return "-"
    seconds = (datetime.now(UTC) - seen).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return "now"


def _term_width() -> int:
    return max(80, min(shutil.get_terminal_size((100, 24)).columns, 140))


def _summarize_row(row: dict[str, Any]) -> dict[str, Any]:
    """A row as this command reports it: with its ref, without the hourly sparkline that
    dominates the endpoint's bytes."""
    return {"ref": _ref(row["fingerprint"]), **{key: value for key, value in row.items() if key != "trend_24h"}}


def _render_rows(rows: list[dict[str, Any]]) -> None:
    """The failure table shared by the digest and search."""
    test_width = max(24, _term_width() - 74)
    click.echo(f"  {'REF':<10}{'STATE':<22}{'OCC':>4}{'BR':>4}{'MSTR':>6}{'LAST':>7}  {'24H':<24}  TEST")
    for row in rows:
        click.echo(
            f"  {_ref(row['fingerprint']):<10}{row.get('state', '-'):<22}"
            f"{row.get('occurrences', 0):>4}{row.get('branches', 0):>4}{row.get('master_hits', 0):>6}"
            f"{_ago(row.get('last_seen')):>7}  {_spark(row.get('trend_24h') or []):<24}  "
            f"{_short(str(row.get('test_id', '')), test_width)}"
        )


def _render_master(health: dict[str, Any]) -> None:
    failing = health.get("failing_workflows") or 0
    settled = health.get("settled_workflows") or 0
    verdict = click.style("RED", fg="red", bold=True) if failing else click.style("OK", fg="green", bold=True)
    click.echo(
        f"{health.get('default_branch') or 'default branch':<20}{verdict}    {failing} of {settled} workflows failing on their latest run"
    )
    for name in health.get("failing_workflow_names") or []:
        click.echo(f"{'':<20}  {name}")


def _render_broken(broken: dict[str, Any], *, limit: int) -> None:
    rows = broken.get("rows") or []
    click.echo(f"{'broken tests':<20}{len(rows)} distinct failures over {broken.get('window_days')}d")
    for state, count in _state_counts(rows).items():
        if count:
            click.echo(f"{'':<20}{state:<22}{count:>4}")
    shown = rows if limit == 0 else rows[:limit]
    if shown:
        click.echo("")
        _render_rows(shown)
    if len(shown) < len(rows) or broken.get("truncated"):
        cap = " (endpoint cap reached)" if broken.get("truncated") else ""
        click.echo(f"\n  Showing {len(shown)} of {len(rows)}{cap} — `hogli ci:insights view <REF>` for one failure.")
    jobs = broken.get("breaking_master_jobs") or []
    if jobs:
        click.echo(f"\n  Jobs red on the default branch now: {', '.join(str(job) for job in jobs[:4])}")


def _render_master_failures(groups: list[dict[str, Any]]) -> None:
    click.echo(f"{'master failures':<20}grouped, last 24h — covers the runners fingerprinting cannot group yet")
    if not groups:
        click.echo(f"{'':<20}none")
        return
    for group in groups[:_DIGEST_ROWS]:
        click.echo(
            f"  {group.get('run_count', 0):>4}  {_short(str(group.get('workflow_name') or '-'), 22):<24}"
            f"{_short(str(group.get('failed_job') or '(workflow level)'), 34):<36}"
            f"{_ago(group.get('last_seen')):>7}  {group.get('latest_run_id', '-')}"
        )


def _render_branch(branch: str, matches: list[dict[str, Any]]) -> None:
    click.echo(f"{'your branch':<20}{branch}")
    if not matches:
        click.echo(f"{'':<20}no PR found — not pushed yet, or a fork")
        return
    for match in matches[:3]:
        click.echo(f"{'':<20}PR #{match.get('number')} ({match.get('state') or 'unknown'}) {match.get('title') or ''}")


def _state_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {state: sum(1 for row in rows if row.get("state") == state) for state in _STATE_MEANINGS}


def _settle(futures: dict[str, Future[Any]]) -> dict[str, tuple[Any, _ApiError | None]]:
    """Collect each section's result or its error, so one failed read does not take the rest
    of the digest with it — a read is worth most during the partial outage that broke it."""
    settled: dict[str, tuple[Any, _ApiError | None]] = {}
    for name, future in futures.items():
        try:
            settled[name] = (future.result(), None)
        except _ApiError as exc:
            settled[name] = (None, exc)
    return settled


def _gather(api: _Api, branch: str | None) -> dict[str, tuple[Any, _ApiError | None]]:
    """Every digest section, read concurrently so the digest costs the slowest call."""
    calls: dict[str, Callable[[], Any]] = {
        "master": lambda: api.get("current_branch_health"),
        "broken": lambda: api.get("broken_tests"),
        "master_failures": lambda: api.get("master_failures", date_from="-24h"),
    }
    if branch:
        calls["branch"] = lambda: api.get("resolve_branch", branch=branch)
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        settled = _settle({name: pool.submit(call) for name, call in calls.items()})
    errors = [error for _, error in settled.values() if error is not None]
    # A credential or flag problem is global, not one section's bad luck — surface it whole.
    fatal = next((error for error in errors if error.exit_code == _EXIT_NOT_CONFIGURED), None)
    # Degradation is for a partial outage. When nothing came back there is no digest to
    # render, and exiting 0 over a page of "unavailable" would read as "CI is fine".
    if fatal or len(errors) == len(settled):
        raise fatal or errors[0]
    return settled


def _emit_json(payload: Any) -> NoReturn:
    click.echo(json.dumps(payload, indent=2, default=str))
    raise SystemExit(0)


@dataclass(frozen=True, kw_only=True)
class _Options:
    """The options every subcommand shares, declared once by ``_common_options``."""

    repo: str | None
    project: str
    host: str
    timeout: float
    output_format: str
    limit: int

    def api(self) -> _Api:
        return _Api(host=self.host.rstrip("/"), project_id=self.project, token=_token(), timeout=self.timeout)

    def json(self) -> bool:
        if self.output_format == "json":
            return True
        return self.output_format == "auto" and not sys.stdout.isatty()


def _options(ctx: click.Context, kwargs: dict[str, Any]) -> _Options:
    """The shared options, resolved across both places they can be given.

    They are declared on the group *and* on every subcommand, so click parses
    ``ci:insights --json view x`` into the group and ``ci:insights view x --json`` into the
    subcommand. Taking either set alone silently drops the other half, which answers about the
    wrong repo or host, so merge them: subcommand-explicit beats group-explicit beats default.
    """
    given = {
        name: value for name, value in kwargs.items() if ctx.get_parameter_source(name) is not ParameterSource.DEFAULT
    }
    # `--json` is documented as shorthand for `--format json`, so collapse it into that one
    # field before merging. Kept separate, the two could disagree across the group/subcommand
    # boundary and `--json view x --format text` would silently print JSON.
    if given.pop("as_json", False):
        given["output_format"] = "json"
    inherited = ctx.parent.obj if ctx.parent is not None and isinstance(ctx.parent.obj, dict) else {}
    ctx.obj = given
    merged = {**kwargs, **inherited, **given}
    merged.pop("as_json", None)
    return _Options(**merged)


def _common_options(func: Callable[..., None]) -> Callable[..., None]:
    """Stack the shared options onto every command, so they can be passed either before or
    after the subcommand (``ci:insights view <ref> --json``, as the old surface allowed)."""
    options = [
        click.option("--repo", help="'owner/name' to read; defaults to the origin remote."),
        click.option(
            "--project",
            default=lambda: os.environ.get("POSTHOG_CI_INSIGHTS_PROJECT_ID") or _DEFAULT_PROJECT_ID,
            help="PostHog project id holding the GitHub source.",
        ),
        click.option(
            "--host",
            default=lambda: os.environ.get("POSTHOG_CI_INSIGHTS_HOST") or _DEFAULT_HOST,
            help="PostHog host to read from.",
        ),
        click.option("--timeout", default=30.0, show_default=True, help="Per-request timeout in seconds."),
        click.option("--json", "as_json", is_flag=True, help="Shorthand for --format json."),
        click.option(
            "--format",
            "output_format",
            type=click.Choice(["auto", "text", "json"]),
            default="auto",
            show_default=True,
            help="'auto' emits JSON when stdout is not a terminal.",
        ),
        click.option("--limit", default=_DIGEST_ROWS, show_default=True, help="Failures to show; 0 for every row."),
    ]
    for option in reversed(options):
        func = option(func)
    return func


# Each entry point resolves credentials in its own body rather than the group callback, so
# `--help` (which short-circuits before the body) works with nothing configured. SystemExit
# is used throughout — the telemetry wrapper records its code, unlike click's ctx.exit().
@click.group(
    name="ci:insights",
    invoke_without_command=True,
    help="What's broken in CI right now, from engineering analytics.",
)
@_common_options
@click.pass_context
def ci_insights(ctx: click.Context, **kwargs: Any) -> None:
    options = _options(ctx, kwargs)
    if ctx.invoked_subcommand is None:
        _digest(options)


def _digest(options: _Options) -> NoReturn:
    try:
        api = _resolve_source(options.api(), options.repo)
        branch = _current_branch()
        sections = _gather(api, branch)
    except _ApiError as exc:
        _fail(exc)

    broken = sections["broken"][0] or {}
    rows = broken.get("rows") or []
    shown = rows if options.limit == 0 else rows[: options.limit]
    if options.json():
        _emit_json(
            {
                "repo": api.repo,
                "source_id": api.source_id,
                "branch": branch,
                "unavailable": {name: error.message for name, (_, error) in sections.items() if error is not None},
                "master": sections["master"][0],
                "broken_tests": {
                    "window_days": broken.get("window_days"),
                    "total": len(rows),
                    "shown": len(shown),
                    "truncated": bool(broken.get("truncated")),
                    "state_counts": _state_counts(rows),
                    "breaking_master_jobs": broken.get("breaking_master_jobs") or [],
                    "rows": [_summarize_row(row) for row in shown],
                },
                "master_failures": sections["master_failures"][0],
                "branch_pull_requests": sections["branch"][0] if "branch" in sections else None,
            }
        )

    renderers: dict[str, Callable[[Any], None]] = {
        "master": _render_master,
        "broken": lambda data: _render_broken(data, limit=options.limit),
        "master_failures": _render_master_failures,
    }
    if branch:
        renderers["branch"] = lambda data: _render_branch(branch, data)

    click.secho(f"{api.repo} · CI insights · {options.host}", bold=True)
    for name, render in renderers.items():
        data, error = sections[name]
        click.echo("")
        if error is not None:
            click.secho(f"{_SECTION_LABELS[name]:<20}(unavailable: {error.message})", fg="yellow")
        else:
            render(data)
    click.echo(f"\n{_CAVEATS}")
    raise SystemExit(0)


@ci_insights.command(name="search", help="Match a failure by test name or error text.")
@click.argument("query")
@click.option(
    "--days",
    default=_SEARCH_DEFAULT_DAYS,
    show_default=True,
    help="Window for the test-health queue (max 30). Error text is only searchable over the last 2 days.",
)
@_common_options
@click.pass_context
def search(ctx: click.Context, query: str, days: int, **kwargs: Any) -> NoReturn:
    options = _options(ctx, kwargs)
    needle = query.lower()
    try:
        api = _resolve_source(options.api(), options.repo)
        with ThreadPoolExecutor(max_workers=2) as pool:
            sections = _settle(
                {
                    "broken": pool.submit(lambda: api.get("broken_tests")),
                    "flaky": pool.submit(
                        lambda: api.get("flaky_tests", date_from=f"-{days}d", limit=_FLAKY_SCAN_LIMIT)
                    ),
                }
            )
        for _, error in sections.values():
            if error is not None:
                raise error
    except _ApiError as exc:
        _fail(exc)

    broken = [
        row
        for row in (sections["broken"][0] or {}).get("rows") or []
        if any(needle in str(row.get(field, "")).lower() for field in ("test_id", "error_signature", "job_name"))
    ]
    flaky = [
        item
        for item in (sections["flaky"][0] or {}).get("items") or []
        if any(needle in str(item.get(field, "")).lower() for field in ("nodeid", "selector"))
    ]
    if options.json():
        _emit_json({"query": query, "broken_tests": [_summarize_row(row) for row in broken], "flaky_tests": flaky})

    # Two sections, never one merged ranking: these are different grains (failure lines from
    # Logs vs CI runs from Traces) over different windows, and fusing them would invent a
    # flaky-versus-broken verdict neither endpoint made.
    click.secho("broken tests        live failures, last 2 days", bold=True)
    if broken:
        _render_rows(broken[:_SEARCH_ROWS])
    else:
        click.echo(f"{'':<20}no match")
    click.echo("")
    click.secho(f"test health         ranked by blast radius, last {days} days", bold=True)
    if flaky:
        _render_flaky(flaky[:_SEARCH_ROWS])
    else:
        click.echo(f"{'':<20}no match")
    if not broken and not flaky:
        click.echo(
            "\nError text is only searchable over the last 2 days, and only for pytest failures. For older or\n"
            "non-pytest text, use the investigating-ci-failures skill's SQL over engineering_analytics_ci_failures."
        )
    raise SystemExit(0)


def _render_flaky(items: list[dict[str, Any]]) -> None:
    click.echo(f"  {'CLASSIFICATION':<24}{'RUNS':>5}{'PRS':>5}{'MSTR':>6}  TEST")
    for item in items:
        click.echo(
            f"  {item.get('classification', '-'):<24}{item.get('failed_run_count', 0):>5}"
            f"{item.get('failed_pr_count', 0):>5}{item.get('master_failed_run_count', 0):>6}  "
            f"{_short(str(item.get('selector') or item.get('nodeid', '')), max(24, _term_width() - 46))}"
        )


@ci_insights.command(name="view", help="Show one failure, optionally with its failing log lines.")
@click.argument("ref")
@click.option("--logs", "with_logs", is_flag=True, help="Include the thinned failing log lines from its latest run.")
@_common_options
@click.pass_context
def view(ctx: click.Context, ref: str, with_logs: bool, **kwargs: Any) -> NoReturn:
    options = _options(ctx, kwargs)
    try:
        api = _resolve_source(options.api(), options.repo)
        row = _resolve_ref((api.get("broken_tests") or {}).get("rows") or [], ref)
        run_id = row.get("latest_run_id")
        logs = api.get("run_failure_logs", run_id=run_id) if with_logs and run_id else None
    except _ApiError as exc:
        _fail(exc)
    if options.json():
        _emit_json({**_summarize_row(row), "logs": logs})

    state = str(row.get("state", ""))
    click.secho(f"{_ref(row['fingerprint'])}  {row.get('test_id')}", bold=True)
    click.echo(f"\n  {'state':<18}{state} — {_STATE_MEANINGS.get(state, 'unclassified')}")
    for label, key in (
        ("error", "error_signature"),
        ("job", "job_name"),
        ("repo", "repo"),
        ("occurrences", "occurrences"),
        ("branches", "branches"),
        ("master hits", "master_hits"),
        ("first seen", "first_seen"),
        ("last seen", "last_seen"),
        ("latest run", "latest_run_id"),
        ("latest branch", "latest_branch"),
    ):
        click.echo(f"  {label:<18}{row.get(key)}")
    trend = row.get("trend_24h") or []
    click.echo(f"  {'last 24h':<18}{_spark(trend)}  ({sum(trend)} failures, oldest hour first)")
    if with_logs:
        # An empty dict renders the same "no logs" note as an empty response, so asking for
        # logs never silently prints nothing.
        _render_logs(logs or {})
    click.echo(f"\n{_CAVEATS}")
    raise SystemExit(0)


def _render_logs(logs: dict[str, Any]) -> None:
    """The thinned failure region per failed job. Jobs carry an id but no name, so the run
    id and branch are the only anchors back to GitHub."""
    if not logs.get("logs_available"):
        click.echo("\n  No failure logs — the run did not fail, or its logs aged out of the short Logs retention.")
        return
    for job in logs.get("jobs") or []:
        click.echo(
            f"\n  job {job.get('job_id')} · run {job.get('run_id')} · {job.get('conclusion')} · {job.get('branch')}"
        )
        for line in job.get("lines") or []:
            number = line.get("original_line")
            click.echo(f"    {str(number) if number else '·':>7}  {line.get('text', '')}")
        if job.get("truncated"):
            click.echo("    (per-job line cap reached)")
