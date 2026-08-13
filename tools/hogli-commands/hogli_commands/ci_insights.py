"""CI insights for the current repo + branch, read from PostHog's engineering analytics.

    hogli ci:insights                       # digest for the current repo + branch
    hogli ci:insights search "<error>"      # match a failure by test name or error text
    hogli ci:insights view <ref> [--logs]   # one failure, with its failing log lines

A REST client over the named ``engineering_analytics`` endpoints, the same ones the in-app UI
and the MCP tools read, so the domain rules are not copied here. This module only picks
endpoints, summarizes, and renders.

Missing or rejected credentials exit ``78`` (sysexits ``EX_CONFIG``) so the
debugging-ci-failures skill can branch to its read-only ``gh`` fallback on the exit code
rather than on message text. Diagnostics go to stderr, keeping stdout parseable.

Output is JSON when stdout is not a terminal, so piped and agent callers get structure without
passing a flag, and ``--json`` forces it in a tty. That JSON is this command's own summarized
shape rather than an endpoint passthrough, because ``broken_tests`` alone returns 200 rows whose
bytes are mostly hourly sparklines.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import hashlib
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, NoReturn

import click
import requests
from click.core import ParameterSource

from hogli_commands import posthog_auth

_DEFAULT_HOST = "https://us.posthog.com"
# The project holding the synced PostHog/posthog GitHub source. Committed rather than configured
# because a project id is not a secret, the same reason hogli.yaml commits the telemetry write key.
_DEFAULT_PROJECT_ID = "2"

# The one scope these endpoints require, so a CI-triage credential cannot write anywhere.
_SCOPES = ("engineering_analytics:read",)

_EXIT_NOT_CONFIGURED = posthog_auth.EXIT_NOT_CONFIGURED

_DIGEST_ROWS = 8
_MAX_LISTED_CANDIDATES = 10
_SEARCH_DEFAULT_DAYS = 7
# Mirrors MAX_FLAKY_WINDOW_DAYS in products/engineering_analytics/backend/logic/suite_health.py.
_MAX_FLAKY_DAYS = 30
_FLAKY_SCAN_LIMIT = 200
# Below this, a ref prefix matches too much to be a useful handle.
_MIN_REF_PREFIX = 4

# BrokenTestState, most urgent first. The endpoint already returns rows in this order, so this
# drives the count summary only, never a client-side re-sort of the rows, which would put the
# classifier's judgement in a second place.
_STATE_MEANINGS: dict[str, str] = {
    "breaking_master": "failing on the default branch, and that job's latest run is still red",
    "blocking_merge_queue": "failing only on merge-queue gate branches, holding up landings on a commit the PR's own CI passed",
    "novel_burst": "first seen within a day and already spreading across branches, not on trunk yet",
    "potentially_resolved": "hit the default branch but that job is green again",
    "flaky": "sporadic across two or more branches over more than a day",
    "pr_only": "confined to one branch, so it is one PR's own problem",
}

_SPARK_LEVELS = " ▁▂▃▄▅▆▇█"

_SECTION_LABELS = {
    "master": "default branch",
    "broken": "broken tests",
    "master_failures": "master failures",
    "branch": "your branch",
}

# The JSON payload key each internal section name lands under, so `_unavailable` can name what a
# consumer actually reads.
_SECTION_KEYS = {
    "master": "master",
    "broken": "broken_tests",
    "master_failures": "master_failures",
    "branch": "branch_pull_requests",
}

# `search` reads a different pair of sections than the digest.
_SEARCH_SECTION_KEYS = {"broken": "broken_tests", "flaky": "flaky_tests"}

_CAVEATS = (
    "Fingerprints are pytest-only, so jest/playwright/cargo breakage shows up under master failures, not above.\n"
    "Counts are absolute, never rates, because passing runs are not in this data.\n"
    "A run's conclusion can lag until GitHub's webhook settles it; confirm a specific run with `gh`."
)


class _ApiError(Exception):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def _fail(error: _ApiError) -> NoReturn:
    click.secho(error.message, fg="red", err=True)
    raise SystemExit(error.exit_code)


def _request(url: str, *, token: str, params: dict[str, Any], timeout: float) -> requests.Response:
    """One authenticated GET, and the only HTTP call in the module, so tests replace it wholesale."""
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
    """The API's own explanation, user-safe on every status mapped in ``_explain``."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(body, dict):
        return str(body.get("detail") or body)[:400]
    return str(body)[:400]


def _explain(response: requests.Response, action: str, *, host: str, project_id: str) -> _ApiError:
    """An HTTP failure, restated as the next thing the reader should do about it."""
    detail = _detail(response)
    status = response.status_code
    if status == 401:
        return _ApiError(
            f"{host} rejected the credential. It may be revoked, or issued for a different region.\n"
            "  Run `hogli auth:posthog:logout` then `hogli auth:posthog:login` to re-authorize.",
            exit_code=_EXIT_NOT_CONFIGURED,
        )
    if status == 403 and "scope" in detail:
        return _ApiError(
            "The credential lacks 'engineering_analytics:read'.\n  Run `hogli auth:posthog:login` to authorize it.",
            exit_code=_EXIT_NOT_CONFIGURED,
        )
    if status == 403:
        return _ApiError(
            f"{detail}\n  Engineering analytics is flag-gated. Ask #team-devex to enable it for your account.",
            exit_code=_EXIT_NOT_CONFIGURED,
        )
    if status == 400 and "source" in detail:
        return _ApiError(
            f"{detail}\n  No GitHub source readable in project {project_id}. Check the project id, and that "
            "your user has warehouse access to the source."
        )
    if status == 404:
        return _ApiError(f"No {action} endpoint at {host} for project {project_id}. The project id may be wrong.")
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
        return replace(self, source_id=source_id, repo=repo)

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
        raise _ApiError("Could not read an 'owner/name' repo from the origin remote. Pass --repo.")
    for entry in entries:
        if str(entry.get("repo", "")).lower() == wanted and entry.get("synced"):
            return api.bound(source_id=str(entry["id"]), repo=str(entry["repo"]))
    readable = ", ".join(sorted(str(entry.get("repo")) for entry in entries if entry.get("synced"))) or "none"
    raise _ApiError(f"No synced GitHub source for {wanted} in project {api.project_id}. Readable repos: {readable}.")


def _ref(fingerprint: str) -> str:
    """An 8-hex handle for a failure fingerprint, usable as an argv token.

    The fingerprint is ``test_id | error_signature``, so it carries spaces and a pipe. Hashing its
    content keeps the handle stable across invocations with no cached state, and changes it exactly
    when the fingerprint does (the fingerprint recipe is pytest-only v1 and evolves).
    """
    return hashlib.blake2s(fingerprint.encode(), digest_size=4).hexdigest()


def _resolve_ref(rows: list[dict[str, Any]], ref: str) -> dict[str, Any]:
    """The one row ``ref`` names, from a handle, handle prefix, full fingerprint, or test-id
    substring. Matching several rows is an error, never a guess at which one was meant."""
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
    listed = "\n".join(
        f"  {_ref(row['fingerprint'])}  {row.get('test_id')}" for row in candidates[:_MAX_LISTED_CANDIDATES]
    )
    raise _ApiError(f"{ref!r} matches {len(candidates)} failures:\n{listed}")


def _spark(counts: list[int]) -> str:
    """A one-cell-per-hour histogram, scaled to its own peak.

    An hour with no failures is blank rather than the shortest bar, because a row of shortest bars
    reads as "it failed a little, constantly".
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
    """A row as this command reports it: with its ref, and without the hourly sparkline that
    dominates the endpoint's bytes."""
    return {"ref": _ref(row["fingerprint"]), **{key: value for key, value in row.items() if key != "trend_24h"}}


def _capped(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """`--limit 0` asks for every row."""
    return rows if limit == 0 else rows[:limit]


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
    shown = _capped(rows, limit)
    if shown:
        click.echo("")
        _render_rows(shown)
    if len(shown) < len(rows) or broken.get("truncated"):
        cap = " (endpoint cap reached)" if broken.get("truncated") else ""
        click.echo(f"\n  Showing {len(shown)} of {len(rows)}{cap}. `hogli ci:insights view <REF>` shows one failure.")
    jobs = broken.get("breaking_master_jobs") or []
    if jobs:
        click.echo(f"\n  Jobs red on the default branch now: {', '.join(str(job) for job in jobs[:4])}")


def _render_master_failures(groups: list[dict[str, Any]]) -> None:
    click.echo(f"{'master failures':<20}grouped, last 24h, covering the runners fingerprinting cannot group yet")
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
        click.echo(f"{'':<20}no PR found: not pushed yet, or a fork")
        return
    for match in matches[:3]:
        click.echo(f"{'':<20}PR #{match.get('number')} ({match.get('state') or 'unknown'}) {match.get('title') or ''}")


def _state_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {state: sum(1 for row in rows if row.get("state") == state) for state in _STATE_MEANINGS}


@dataclass(frozen=True, kw_only=True)
class _Section:
    """One endpoint read: its payload, or the error standing in for it."""

    data: Any = None
    error: _ApiError | None = None


_Sections = dict[str, _Section]


def _read(calls: dict[str, Callable[[], Any]]) -> _Sections:
    """Read every section concurrently, so the whole read costs the slowest call.

    Each section's error is kept beside its slot rather than raised, because one failed read must
    not take the rest with it: a read is worth most during the partial outage that broke it.
    """
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {name: pool.submit(call) for name, call in calls.items()}
    settled: _Sections = {}
    for name, future in futures.items():
        try:
            settled[name] = _Section(data=future.result())
        except _ApiError as exc:
            settled[name] = _Section(error=exc)
    return settled


def _unavailable(sections: _Sections, keys: dict[str, str]) -> dict[str, str]:
    """The sections that failed, keyed by the payload key each lands under, so a consumer can join
    the failure to the section it is missing. The internal names would not do: `broken` names
    nothing in the payload, and `branch` collides with the branch name."""
    return {keys[name]: section.error.message for name, section in sections.items() if section.error is not None}


def _gather(api: _Api, branch: str | None) -> _Sections:
    calls: dict[str, Callable[[], Any]] = {
        "master": lambda: api.get("current_branch_health"),
        "broken": lambda: api.get("broken_tests"),
        "master_failures": lambda: api.get("master_failures", date_from="-24h"),
    }
    if branch:
        calls["branch"] = lambda: api.get("resolve_branch", branch=branch)
    sections = _read(calls)
    errors = [section.error for section in sections.values() if section.error is not None]
    # A credential or flag problem is global rather than one section's bad luck, so surface it whole.
    fatal = next((error for error in errors if error.exit_code == _EXIT_NOT_CONFIGURED), None)
    # Degradation is for a partial outage. When nothing came back there is no digest to render, and
    # exiting 0 over a page of "unavailable" would read as "CI is fine".
    if fatal or len(errors) == len(sections):
        raise fatal or errors[0]
    return sections


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
        host = self.host.rstrip("/")
        try:
            token = posthog_auth.token(scopes=_SCOPES, host=host)
        except posthog_auth.AuthError as exc:
            # Re-raised as this module's error so every failure exits through `_fail`, keeping the
            # exit code and the stderr-only rule in one place.
            raise _ApiError(exc.message, exit_code=exc.exit_code) from exc
        return _Api(host=host, project_id=self.project, token=token, timeout=self.timeout)

    def emits_json(self) -> bool:
        if self.output_format == "json":
            return True
        return self.output_format == "auto" and not sys.stdout.isatty()


def _options(ctx: click.Context, kwargs: dict[str, Any]) -> _Options:
    """The shared options, merged across both places click can put them.

    They are declared on the group and on every subcommand, so ``ci:insights --json view x`` parses
    into the group while ``ci:insights view x --json`` parses into the subcommand. Reading either
    set alone drops the other half and answers about the wrong repo or host, so precedence runs
    subcommand-explicit, then group-explicit, then default.
    """
    given = {
        name: value for name, value in kwargs.items() if ctx.get_parameter_source(name) is not ParameterSource.DEFAULT
    }
    # `--json` is documented as shorthand for `--format json`, so collapse it into that one field
    # before merging. Kept separate, the two could disagree across the group/subcommand boundary and
    # `--json view x --format text` would silently print JSON.
    if given.pop("as_json", False):
        given["output_format"] = "json"
    inherited = ctx.parent.obj if ctx.parent is not None and isinstance(ctx.parent.obj, dict) else {}
    ctx.obj = given
    merged = {**kwargs, **inherited, **given}
    merged.pop("as_json", None)
    return _Options(**merged)


def _common_options(func: Callable[..., None]) -> Callable[..., None]:
    """Stack the shared options onto a command, so they parse either before or after the
    subcommand. `_options` merges the two sides."""
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


# Each entry point resolves credentials in its own body rather than the group callback, so `--help`
# (which short-circuits before the body) works with nothing configured. Every exit raises SystemExit
# because the telemetry wrapper records its code, which click's ctx.exit() does not reach.
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


def _digest_payload(api: _Api, branch: str | None, sections: _Sections, limit: int) -> dict[str, Any]:
    """The digest as `--json` reports it, summarized rather than passed through."""
    broken = sections["broken"].data or {}
    rows = broken.get("rows") or []
    shown = _capped(rows, limit)
    return {
        "repo": api.repo,
        "source_id": api.source_id,
        "branch": branch,
        "unavailable": _unavailable(sections, _SECTION_KEYS),
        "master": sections["master"].data,
        # None, never a zero-filled section: a failed read rendered as `total: 0` is a complete,
        # well-formed claim that nothing is broken, and JSON is the default for every non-tty caller.
        "broken_tests": None
        if sections["broken"].error is not None
        else {
            "window_days": broken.get("window_days"),
            "total": len(rows),
            "shown": len(shown),
            "truncated": bool(broken.get("truncated")),
            "state_counts": _state_counts(rows),
            "breaking_master_jobs": broken.get("breaking_master_jobs") or [],
            "rows": [_summarize_row(row) for row in shown],
        },
        "master_failures": sections["master_failures"].data,
        "branch_pull_requests": sections["branch"].data if "branch" in sections else None,
    }


def _digest(options: _Options) -> NoReturn:
    try:
        api = _resolve_source(options.api(), options.repo)
        branch = _current_branch()
        sections = _gather(api, branch)
    except _ApiError as exc:
        _fail(exc)

    if options.emits_json():
        _emit_json(_digest_payload(api, branch, sections, options.limit))

    renderers: dict[str, Callable[[Any], None]] = {
        "master": _render_master,
        "broken": lambda data: _render_broken(data, limit=options.limit),
        "master_failures": _render_master_failures,
    }
    if branch:
        renderers["branch"] = lambda data: _render_branch(branch, data)

    click.secho(f"{api.repo} · CI insights · {options.host}", bold=True)
    for name, render in renderers.items():
        section = sections[name]
        click.echo("")
        if section.error is not None:
            click.secho(f"{_SECTION_LABELS[name]:<20}(unavailable: {section.error.message})", fg="yellow")
        else:
            render(section.data)
    click.echo(f"\n{_CAVEATS}")
    raise SystemExit(0)


@ci_insights.command(name="search", help="Match a failure by test name or error text.")
@click.argument("query")
@click.option(
    "--days",
    # Ranged rather than clamped: the backend rejects a wider window, and silently narrowing the
    # window someone asked for would answer a different question than the one they posed.
    type=click.IntRange(1, _MAX_FLAKY_DAYS),
    default=_SEARCH_DEFAULT_DAYS,
    show_default=True,
    help=f"Window for the test-health queue (max {_MAX_FLAKY_DAYS}). "
    "Error text is only searchable over the last 2 days.",
)
@_common_options
@click.pass_context
def search(ctx: click.Context, query: str, days: int, **kwargs: Any) -> NoReturn:
    options = _options(ctx, kwargs)
    needle = query.lower()
    try:
        api = _resolve_source(options.api(), options.repo)
        sections = _read(
            {
                "broken": lambda: api.get("broken_tests"),
                "flaky": lambda: api.get("flaky_tests", date_from=f"-{days}d", limit=_FLAKY_SCAN_LIMIT),
            }
        )
        errors = [section.error for section in sections.values() if section.error is not None]
        # One section failing must not discard the other: they are independent reads, and the digest
        # already degrades this way. Both failing means there is nothing to show.
        if len(errors) == len(sections):
            raise errors[0]
    except _ApiError as exc:
        _fail(exc)

    broken = [
        row
        for row in (sections["broken"].data or {}).get("rows") or []
        if any(needle in str(row.get(field, "")).lower() for field in ("test_id", "error_signature", "job_name"))
    ]
    flaky = [
        item
        for item in (sections["flaky"].data or {}).get("items") or []
        if any(needle in str(item.get(field, "")).lower() for field in ("nodeid", "selector"))
    ]
    shown_broken, shown_flaky = _capped(broken, options.limit), _capped(flaky, options.limit)
    if options.emits_json():
        _emit_json(
            {
                "query": query,
                "unavailable": _unavailable(sections, _SEARCH_SECTION_KEYS),
                "broken_tests": [_summarize_row(row) for row in shown_broken],
                "flaky_tests": shown_flaky,
                "truncated": len(shown_broken) < len(broken) or len(shown_flaky) < len(flaky),
            }
        )

    # Two sections, never one merged ranking: these are different grains (failure lines from Logs
    # versus CI runs from Traces) over different windows, so fusing them would invent a
    # flaky-versus-broken verdict neither endpoint made.
    click.secho("broken tests        live failures, last 2 days", bold=True)
    if broken:
        _render_rows(shown_broken)
        _note_truncation(len(shown_broken), len(broken))
    else:
        click.echo(f"{'':<20}no match")
    click.echo("")
    click.secho(f"test health         ranked by blast radius, last {days} days", bold=True)
    if flaky:
        _render_flaky(shown_flaky)
        _note_truncation(len(shown_flaky), len(flaky))
    else:
        click.echo(f"{'':<20}no match")
    for name, section in sections.items():
        if section.error is not None:
            click.secho(f"\n{_SEARCH_SECTION_KEYS[name]} unavailable: {section.error.message}", fg="yellow")
    if not broken and not flaky:
        click.echo(
            "\nError text is only searchable over the last 2 days, and only for pytest failures. For older or\n"
            "non-pytest text, use the investigating-ci-failures skill's SQL over engineering_analytics_ci_failures."
        )
    raise SystemExit(0)


def _note_truncation(shown: int, total: int) -> None:
    """Say what was dropped. Text capping silently while ``--json`` returns everything leaves the two
    output shapes disagreeing on how many matches exist."""
    if shown < total:
        click.echo(f"{'':<20}Showing {shown} of {total}. Raise --limit, or 0 for every row.")


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
        # The endpoint writes `latest_run_id or 0`, so 0 is "no run id recorded" rather than a run.
        run_id = row.get("latest_run_id") or 0
        logs = api.get("run_failure_logs", run_id=run_id) if with_logs and run_id else None
    except _ApiError as exc:
        _fail(exc)
    if options.emits_json():
        _emit_json({**_summarize_row(row), "logs": logs})

    state = str(row.get("state", ""))
    click.secho(f"{_ref(row['fingerprint'])}  {row.get('test_id')}", bold=True)
    click.echo(f"\n  {'state':<18}{state}: {_STATE_MEANINGS.get(state, 'unclassified')}")
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
        if not run_id:
            click.echo("\n  No failure logs: this failure has no run id recorded, so there is nothing to fetch.")
        else:
            # An empty dict renders the same "no logs" note as an empty response, so asking for
            # logs never silently prints nothing.
            _render_logs(logs or {})
    click.echo(f"\n{_CAVEATS}")
    raise SystemExit(0)


def _render_logs(logs: dict[str, Any]) -> None:
    """The thinned failure region per failed job. Jobs carry an id but no name, so the run
    id and branch are the only anchors back to GitHub."""
    if not logs.get("logs_available"):
        click.echo("\n  No failure logs: the run did not fail, or its logs aged out of the short Logs retention.")
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
