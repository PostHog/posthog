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
import unicodedata
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import NoneType, UnionType
from typing import (
    Any,
    Generic,
    Literal,
    NoReturn,
    NotRequired,
    TypedDict,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)
from urllib.parse import ParseResult, urlparse

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
    "blocking_merge_queue": "failed only on merge-queue gate branches on a commit the PR's own CI passed",
    "novel_burst": "first seen within a day and already spreading across branches, not on trunk yet",
    "potentially_resolved": "hit the default branch but that job is green again",
    "flaky": "sporadic across two or more branches over more than a day",
    "pr_only": "limited branch spread; confirm the current run before assigning it to a PR",
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


_BrokenTestState = Literal[
    "breaking_master",
    "blocking_merge_queue",
    "novel_burst",
    "potentially_resolved",
    "flaky",
    "pr_only",
]
_FlakyTestClassification = Literal["confirmed_flake", "suspected_regression", "quarantined"]


class _GitHubSource(TypedDict):
    id: str
    repo: str
    prefix: str
    synced: bool


class _CurrentBranchHealth(TypedDict):
    default_branch: str
    settled_workflows: int
    failing_workflows: int
    failing_workflow_names: list[str]


class _RepoRef(TypedDict):
    provider: str
    owner: str
    name: str


class _MasterFailureGroup(TypedDict):
    repo: _RepoRef
    workflow_name: str
    failed_job: str
    run_count: int
    first_seen: str
    last_seen: str
    latest_run_id: int


class _BrokenTestRow(TypedDict):
    fingerprint: str
    test_id: str
    error_signature: str
    job_name: str
    repo: str
    state: _BrokenTestState
    first_seen: str
    last_seen: str
    occurrences: int
    branches: int
    master_hits: int
    latest_run_id: int
    latest_branch: str
    trend_24h: list[int]


class _BrokenTestSummary(TypedDict):
    ref: str
    fingerprint: str
    test_id: str
    error_signature: str
    job_name: str
    repo: str
    state: _BrokenTestState
    first_seen: str
    last_seen: str
    occurrences: int
    branches: int
    master_hits: int
    latest_run_id: int
    latest_branch: str


class _BrokenTests(TypedDict):
    rows: list[_BrokenTestRow]
    breaking_master_jobs: list[str]
    window_days: int
    truncated: bool
    limit: int


class _FlakyTestItem(TypedDict):
    runner: str
    nodeid: str
    selector: str
    classification: _FlakyTestClassification
    same_commit_recovery_run_count: int
    failed_run_count: int
    failed_pr_count: int
    master_failed_run_count: int
    quarantined_failed_run_count: int
    last_signal_at: str


class _FlakyTests(TypedDict):
    items: list[_FlakyTestItem]
    truncated: bool
    limit: int


class _BranchPRMatch(TypedDict):
    repo: str
    number: int
    title: str | None
    state: str | None


class _FailureLogLine(TypedDict):
    original_line: int | None
    text: str


class _FailureLogJob(TypedDict):
    job_id: int
    run_id: int
    conclusion: str
    branch: str
    original_total_lines: int
    line_count: int
    lines: list[_FailureLogLine]
    truncated: bool


class _RunFailureLogs(TypedDict):
    run_id: int
    logs_available: bool
    jobs: list[_FailureLogJob]
    truncated: bool


def _invalid_payload(action: str, path: str, expected: str) -> NoReturn:
    raise _ApiError(f"{action} returned an invalid payload: {path} must be {expected}.")


def _validate_payload(value: object, expected: object, action: str, path: str = "response") -> None:
    origin = get_origin(expected)
    if is_typeddict(expected):
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            _invalid_payload(action, path, "an object")
        payload = cast(dict[str, object], value)
        fields: dict[str, object] = get_type_hints(expected)
        required = cast(frozenset[str], expected.__required_keys__)
        for key in required:
            if key not in payload:
                _invalid_payload(action, f"{path}.{key}", "present")
        for key, field_type in fields.items():
            if key in payload:
                _validate_payload(payload[key], field_type, action, f"{path}.{key}")
        return
    if origin is list:
        if not isinstance(value, list):
            _invalid_payload(action, path, "an array")
        item_type = get_args(expected)[0]
        for index, item in enumerate(value):
            _validate_payload(item, item_type, action, f"{path}[{index}]")
        return
    if origin in {Union, UnionType}:
        choices = get_args(expected)
        if value is None and NoneType in choices:
            return
        remaining = tuple(choice for choice in choices if choice is not NoneType)
        if len(remaining) == 1:
            _validate_payload(value, remaining[0], action, path)
            return
    if origin is Literal:
        if value not in get_args(expected):
            _invalid_payload(action, path, f"one of {get_args(expected)!r}")
        return
    if expected is int:
        if type(value) is not int:
            _invalid_payload(action, path, "an integer")
        return
    if expected is bool:
        if type(value) is not bool:
            _invalid_payload(action, path, "a boolean")
        return
    if expected is str:
        if not isinstance(value, str):
            _invalid_payload(action, path, "a string")
        return
    raise TypeError(f"Unsupported API payload annotation: {expected!r}")


def _parse_sources(value: object, action: str) -> list[_GitHubSource]:
    expected = list[_GitHubSource]
    _validate_payload(value, expected, action)
    return cast(list[_GitHubSource], value)


def _parse_current_branch_health(value: object, action: str) -> _CurrentBranchHealth:
    _validate_payload(value, _CurrentBranchHealth, action)
    return cast(_CurrentBranchHealth, value)


def _parse_master_failures(value: object, action: str) -> list[_MasterFailureGroup]:
    expected = list[_MasterFailureGroup]
    _validate_payload(value, expected, action)
    return cast(list[_MasterFailureGroup], value)


def _parse_broken_tests(value: object, action: str) -> _BrokenTests:
    _validate_payload(value, _BrokenTests, action)
    return cast(_BrokenTests, value)


def _parse_flaky_tests(value: object, action: str) -> _FlakyTests:
    _validate_payload(value, _FlakyTests, action)
    return cast(_FlakyTests, value)


def _parse_branch_matches(value: object, action: str) -> list[_BranchPRMatch]:
    expected = list[_BranchPRMatch]
    _validate_payload(value, expected, action)
    return cast(list[_BranchPRMatch], value)


def _parse_run_failure_logs(value: object, action: str) -> _RunFailureLogs:
    _validate_payload(value, _RunFailureLogs, action)
    return cast(_RunFailureLogs, value)


def _terminal_text(value: object) -> str:
    return "".join(character for character in str(value) if unicodedata.category(character) not in {"Cc", "Cf"})


def _parse_http_origin(host: str) -> ParseResult | None:
    try:
        parsed = urlparse(host)
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed


class _ApiError(Exception):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        safe_message = "\n".join(_terminal_text(line) for line in message.splitlines())
        super().__init__(safe_message)
        self.message = safe_message
        self.exit_code = exit_code


def _fail(error: _ApiError) -> NoReturn:
    click.secho(error.message, fg="red", err=True)
    raise SystemExit(error.exit_code)


def _request(url: str, *, token: str, params: dict[str, str | int], timeout: float) -> requests.Response:
    """One authenticated GET, and the only HTTP call in the module, so tests replace it wholesale."""
    return requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params,
        timeout=timeout,
    )


def _parse(response: requests.Response, action: str) -> object:
    try:
        payload: object = response.json()
        return payload
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
            "  Run `hogli posthog:logout` then `hogli posthog:login` to re-authorize.",
            exit_code=_EXIT_NOT_CONFIGURED,
        )
    if status == 403 and "scope" in detail:
        return _ApiError(
            "The credential lacks 'engineering_analytics:read'.\n  Run `hogli posthog:login` to authorize it.",
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

    def _get(self, action: str, **params: str | int) -> object:
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

    def sources(self) -> list[_GitHubSource]:
        action = "sources"
        return _parse_sources(self._get(action), action)

    def current_branch_health(self) -> _CurrentBranchHealth:
        action = "current_branch_health"
        return _parse_current_branch_health(self._get(action), action)

    def broken_tests(self) -> _BrokenTests:
        action = "broken_tests"
        return _parse_broken_tests(self._get(action), action)

    def master_failures(self) -> list[_MasterFailureGroup]:
        action = "master_failures"
        return _parse_master_failures(self._get(action, date_from="-24h"), action)

    def flaky_tests(self, *, days: int) -> _FlakyTests:
        action = "flaky_tests"
        return _parse_flaky_tests(self._get(action, date_from=f"-{days}d", limit=_FLAKY_SCAN_LIMIT), action)

    def resolve_branch(self, *, branch: str) -> list[_BranchPRMatch]:
        action = "resolve_branch"
        return _parse_branch_matches(self._get(action, branch=branch), action)

    def run_failure_logs(self, *, run_id: int) -> _RunFailureLogs:
        action = "run_failure_logs"
        return _parse_run_failure_logs(self._get(action, run_id=run_id), action)


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
    entries = api.sources()
    wanted = (repo or _origin_repo() or "").lower()
    if not wanted:
        raise _ApiError("Could not read an 'owner/name' repo from the origin remote. Pass --repo.")
    for entry in entries:
        if entry["repo"].lower() == wanted and entry["synced"]:
            return api.bound(source_id=entry["id"], repo=entry["repo"])
    readable = ", ".join(sorted(entry["repo"] for entry in entries if entry["synced"])) or "none"
    raise _ApiError(f"No synced GitHub source for {wanted} in project {api.project_id}. Readable repos: {readable}.")


def _ref(fingerprint: str) -> str:
    """An 8-hex handle for a failure fingerprint, usable as an argv token.

    The fingerprint is ``test_id | error_signature``, so it carries spaces and a pipe. Hashing its
    content keeps the handle stable across invocations with no cached state, and changes it exactly
    when the fingerprint does (the fingerprint recipe is pytest-only v1 and evolves).
    """
    return hashlib.blake2s(fingerprint.encode(), digest_size=4).hexdigest()


def _resolve_ref(rows: list[_BrokenTestRow], ref: str) -> _BrokenTestRow:
    """The one row ``ref`` names, from a handle, handle prefix, full fingerprint, or test-id
    substring. Matching several rows is an error, never a guess at which one was meant."""
    lowered = ref.lower()
    candidates = [row for row in rows if _ref(row["fingerprint"]) == lowered or row["fingerprint"] == ref]
    if not candidates and len(ref) >= _MIN_REF_PREFIX:
        candidates = [row for row in rows if _ref(row["fingerprint"]).startswith(lowered)]
    if not candidates:
        candidates = [row for row in rows if lowered in row["test_id"].lower()]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise _ApiError(f"No current failure matches {ref!r}. Refs come from `hogli ci:insights` or `search`.")
    listed = "\n".join(f"  {_ref(row['fingerprint'])}  {row['test_id']}" for row in candidates[:_MAX_LISTED_CANDIDATES])
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
    text = _terminal_text(text)
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


def _summarize_row(row: _BrokenTestRow) -> _BrokenTestSummary:
    """A row as this command reports it: with its ref, and without the hourly sparkline that
    dominates the endpoint's bytes."""
    return _BrokenTestSummary(
        ref=_ref(row["fingerprint"]),
        fingerprint=row["fingerprint"],
        test_id=row["test_id"],
        error_signature=row["error_signature"],
        job_name=row["job_name"],
        repo=row["repo"],
        state=row["state"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        occurrences=row["occurrences"],
        branches=row["branches"],
        master_hits=row["master_hits"],
        latest_run_id=row["latest_run_id"],
        latest_branch=row["latest_branch"],
    )


_ItemT = TypeVar("_ItemT")


def _capped(rows: list[_ItemT], limit: int) -> list[_ItemT]:
    """`--limit 0` asks for every row."""
    return rows if limit == 0 else rows[:limit]


def _render_rows(rows: list[_BrokenTestRow]) -> None:
    """The failure table shared by the digest and search."""
    test_width = max(24, _term_width() - 74)
    click.echo(f"  {'REF':<10}{'STATE':<22}{'OCC':>4}{'BR':>4}{'MSTR':>6}{'LAST':>7}  {'24H':<24}  TEST")
    for row in rows:
        state = _terminal_text(row["state"])
        click.echo(
            f"  {_ref(row['fingerprint']):<10}{state:<22}"
            f"{row['occurrences']:>4}{row['branches']:>4}{row['master_hits']:>6}"
            f"{_ago(row['last_seen']):>7}  {_spark(row['trend_24h']):<24}  "
            f"{_short(row['test_id'], test_width)}"
        )


def _render_master(health: _CurrentBranchHealth) -> None:
    failing = health["failing_workflows"]
    settled = health["settled_workflows"]
    branch = _terminal_text(health["default_branch"])
    label = f"{branch:<20}"
    # A read that succeeded with nothing behind it is not a green default branch. Rendering it as
    # OK claims every workflow passed, when the truth is that none has settled to be counted.
    if not settled:
        click.echo(f"{label}{click.style('NO DATA', fg='yellow', bold=True)}    no workflow run has settled yet")
        return
    verdict = click.style("RED", fg="red", bold=True) if failing else click.style("OK", fg="green", bold=True)
    click.echo(f"{label}{verdict}    {failing} of {settled} workflows failing on their latest run")
    for name in health["failing_workflow_names"]:
        click.echo(f"{'':<20}  {_terminal_text(name)}")


def _render_broken(broken: _BrokenTests, *, limit: int) -> None:
    rows = broken["rows"]
    click.echo(f"{'broken tests':<20}{len(rows)} distinct failures over {broken['window_days']}d")
    for state, count in _state_counts(rows).items():
        if count:
            click.echo(f"{'':<20}{state:<22}{count:>4}")
    shown = _capped(rows, limit)
    if shown:
        click.echo("")
        _render_rows(shown)
    if len(shown) < len(rows) or broken["truncated"]:
        cap = " (endpoint cap reached)" if broken["truncated"] else ""
        click.echo(f"\n  Showing {len(shown)} of {len(rows)}{cap}. `hogli ci:insights view <REF>` shows one failure.")
    jobs = broken["breaking_master_jobs"]
    if jobs:
        click.echo(f"\n  Jobs red on the default branch now: {', '.join(_terminal_text(job) for job in jobs[:4])}")


def _render_master_failures(groups: list[_MasterFailureGroup]) -> None:
    click.echo(f"{'master failures':<20}grouped over 24h, including runners without fingerprinting")
    if not groups:
        click.echo(f"{'':<20}none")
        return
    for group in groups[:_DIGEST_ROWS]:
        click.echo(
            f"  {group['run_count']:>4}  {_short(group['workflow_name'], 22):<24}"
            f"{_short(group['failed_job'] or '(workflow level)', 34):<36}"
            f"{_ago(group['last_seen']):>7}  {group['latest_run_id']}"
        )


def _render_branch(branch: str, matches: list[_BranchPRMatch]) -> None:
    click.echo(f"{'your branch':<20}{_terminal_text(branch)}")
    if not matches:
        click.echo(f"{'':<20}no open PR found: not pushed yet, no open PR, or a fork")
        return
    for match in matches[:3]:
        number = _terminal_text(match["number"])
        state = _terminal_text(match["state"] or "unknown")
        title = _terminal_text(match["title"] or "")
        click.echo(f"{'':<20}PR #{number} ({state}) {title}")


def _state_counts(rows: list[_BrokenTestRow]) -> dict[str, int]:
    return {state: sum(1 for row in rows if row["state"] == state) for state in _STATE_MEANINGS}


_PayloadT_co = TypeVar("_PayloadT_co", covariant=True)


@dataclass(frozen=True, kw_only=True)
class _Section(Generic[_PayloadT_co]):
    """One endpoint read: its payload, or the error standing in for it."""

    data: _PayloadT_co | None = None
    error: _ApiError | None = None


class _DigestSections(TypedDict):
    master: _Section[_CurrentBranchHealth]
    broken: _Section[_BrokenTests]
    master_failures: _Section[list[_MasterFailureGroup]]
    branch: NotRequired[_Section[list[_BranchPRMatch]]]


class _SearchSections(TypedDict):
    broken: _Section[_BrokenTests]
    flaky: _Section[_FlakyTests]


_PayloadT = TypeVar("_PayloadT")


def _settle(future: Future[_PayloadT]) -> _Section[_PayloadT]:
    """Keep a section's error beside its slot so one failed read does not discard the rest."""
    try:
        return _Section(data=future.result())
    except _ApiError as exc:
        return _Section(error=exc)


def _unavailable(sections: dict[str, _Section[object]], keys: dict[str, str]) -> dict[str, str]:
    """The sections that failed, keyed by the payload key each lands under, so a consumer can join
    the failure to the section it is missing. The internal names would not do: `broken` names
    nothing in the payload, and `branch` collides with the branch name."""
    return {keys[name]: section.error.message for name, section in sections.items() if section.error is not None}


def _gather(api: _Api, branch: str | None) -> _DigestSections:
    """Read every digest section concurrently, so the whole read costs the slowest call."""
    with ThreadPoolExecutor(max_workers=4 if branch else 3) as pool:
        master_future = pool.submit(api.current_branch_health)
        broken_future = pool.submit(api.broken_tests)
        master_failures_future = pool.submit(api.master_failures)
        branch_future = pool.submit(api.resolve_branch, branch=branch) if branch else None
    sections = _DigestSections(
        master=_settle(master_future),
        broken=_settle(broken_future),
        master_failures=_settle(master_failures_future),
    )
    if branch_future is not None:
        sections["branch"] = _settle(branch_future)
    all_sections: list[_Section[object]] = [
        sections["master"],
        sections["broken"],
        sections["master_failures"],
    ]
    if "branch" in sections:
        all_sections.append(sections["branch"])
    errors = [section.error for section in all_sections if section.error is not None]
    # A credential or flag problem is global rather than one section's bad luck, so surface it whole.
    fatal = next((error for error in errors if error.exit_code == _EXIT_NOT_CONFIGURED), None)
    # Degradation is for a partial outage. When nothing came back there is no digest to render, and
    # exiting 0 over a page of "unavailable" would read as "CI is fine".
    if fatal is not None:
        raise fatal
    if len(errors) == len(all_sections):
        raise errors[0]
    return sections


def _emit_json(payload: object) -> NoReturn:
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
        parsed_host = _parse_http_origin(host)
        if parsed_host is None:
            raise _ApiError("--host must be an HTTP(S) origin without credentials, a path, a query, or a fragment.")
        hostname = parsed_host.hostname or ""
        is_posthog_cloud = parsed_host.scheme == "https" and (
            hostname == "posthog.com" or hostname.endswith(".posthog.com")
        )
        if (environment_key := posthog_auth.key_in_env()) and not is_posthog_cloud:
            raise _ApiError(
                f"Refusing to send {environment_key.variable} to {host}.\n"
                f"  Unset it, then run `hogli posthog:login --host {host}` to use a host-bound credential.",
                exit_code=_EXIT_NOT_CONFIGURED,
            )
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
        click.option(
            "--timeout",
            type=click.FloatRange(min=0, min_open=True),
            default=30.0,
            show_default=True,
            help="Per-request timeout in seconds.",
        ),
        click.option("--json", "as_json", is_flag=True, help="Shorthand for --format json."),
        click.option(
            "--format",
            "output_format",
            type=click.Choice(["auto", "text", "json"]),
            default="auto",
            show_default=True,
            help="'auto' emits JSON when stdout is not a terminal.",
        ),
        click.option(
            "--limit",
            type=click.IntRange(min=0),
            default=_DIGEST_ROWS,
            show_default=True,
            help="Failures to show; 0 for every row.",
        ),
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


def _digest_payload(api: _Api, branch: str | None, sections: _DigestSections, limit: int) -> dict[str, object]:
    """The digest as `--json` reports it, summarized rather than passed through."""
    broken = sections["broken"].data
    rows = broken["rows"] if broken is not None else []
    shown = _capped(rows, limit)
    unavailable_sections: dict[str, _Section[object]] = {
        "master": sections["master"],
        "broken": sections["broken"],
        "master_failures": sections["master_failures"],
    }
    if "branch" in sections:
        unavailable_sections["branch"] = sections["branch"]
    return {
        "repo": api.repo,
        "source_id": api.source_id,
        "branch": branch,
        "unavailable": _unavailable(unavailable_sections, _SECTION_KEYS),
        "master": sections["master"].data,
        # None, never a zero-filled section: a failed read rendered as `total: 0` is a complete,
        # well-formed claim that nothing is broken, and JSON is the default for every non-tty caller.
        "broken_tests": None
        if sections["broken"].error is not None
        else {
            "window_days": broken["window_days"] if broken is not None else None,
            "total": len(rows),
            "shown": len(shown),
            "truncated": broken["truncated"] if broken is not None else False,
            "state_counts": _state_counts(rows),
            "breaking_master_jobs": broken["breaking_master_jobs"] if broken is not None else [],
            "rows": [_summarize_row(row) for row in shown],
        },
        "master_failures": sections["master_failures"].data,
        "branch_pull_requests": sections["branch"].data if "branch" in sections else None,
    }


def _render_section(label: str, section: _Section[_PayloadT], render: Callable[[_PayloadT], None]) -> None:
    click.echo("")
    if section.error is not None:
        click.secho(f"{label:<20}(unavailable: {section.error.message})", fg="yellow")
    elif section.data is not None:
        render(section.data)


def _digest(options: _Options) -> NoReturn:
    try:
        api = _resolve_source(options.api(), options.repo)
        branch = _current_branch()
        sections = _gather(api, branch)
    except _ApiError as exc:
        _fail(exc)

    if options.emits_json():
        _emit_json(_digest_payload(api, branch, sections, options.limit))

    click.secho(f"{api.repo} · CI insights · {options.host}", bold=True)
    _render_section(_SECTION_LABELS["master"], sections["master"], _render_master)
    _render_section(
        _SECTION_LABELS["broken"], sections["broken"], lambda data: _render_broken(data, limit=options.limit)
    )
    _render_section(_SECTION_LABELS["master_failures"], sections["master_failures"], _render_master_failures)
    if branch and "branch" in sections:
        _render_section(_SECTION_LABELS["branch"], sections["branch"], lambda data: _render_branch(branch, data))
    click.echo(f"\n{_CAVEATS}")
    raise SystemExit(0)


@ci_insights.command(name="search", help="Match a failure by test name or stable error text.")
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
        with ThreadPoolExecutor(max_workers=2) as pool:
            broken_future = pool.submit(api.broken_tests)
            flaky_future = pool.submit(api.flaky_tests, days=days)
        sections = _SearchSections(broken=_settle(broken_future), flaky=_settle(flaky_future))
        errors = [error for error in (sections["broken"].error, sections["flaky"].error) if error is not None]
        # One section failing must not discard the other: they are independent reads, and the digest
        # already degrades this way. Both failing means there is nothing to show.
        if len(errors) == len(sections):
            raise errors[0]
    except _ApiError as exc:
        _fail(exc)

    broken_payload = sections["broken"].data
    flaky_payload = sections["flaky"].data
    broken = [
        row
        for row in (broken_payload["rows"] if broken_payload is not None else [])
        if any(needle in value.lower() for value in (row["test_id"], row["error_signature"], row["job_name"]))
    ]
    flaky = [
        item
        for item in (flaky_payload["items"] if flaky_payload is not None else [])
        if any(needle in value.lower() for value in (item["nodeid"], item["selector"]))
    ]
    shown_broken, shown_flaky = _capped(broken, options.limit), _capped(flaky, options.limit)
    source_truncated = {
        "broken_tests": broken_payload["truncated"] if broken_payload is not None else False,
        "flaky_tests": flaky_payload["truncated"] if flaky_payload is not None else False,
    }
    truncated_sections = [
        name
        for name, truncated in source_truncated.items()
        if truncated
        or (name == "broken_tests" and len(shown_broken) < len(broken))
        or (name == "flaky_tests" and len(shown_flaky) < len(flaky))
    ]
    if options.emits_json():
        _emit_json(
            {
                "query": query,
                "unavailable": _unavailable(
                    {"broken": sections["broken"], "flaky": sections["flaky"]}, _SEARCH_SECTION_KEYS
                ),
                "broken_tests": None
                if sections["broken"].error is not None
                else [_summarize_row(row) for row in shown_broken],
                "flaky_tests": None if sections["flaky"].error is not None else shown_flaky,
                "truncated": bool(truncated_sections),
                "truncated_sections": truncated_sections,
            }
        )

    # Two sections, never one merged ranking: these are different grains (failure lines from Logs
    # versus CI runs from Traces) over different windows, so fusing them would invent a
    # flaky-versus-broken verdict neither endpoint made.
    click.secho("broken tests        recent failure fingerprints, last 2 days", bold=True)
    if sections["broken"].error is not None:
        click.secho(f"{'':<20}unavailable: {sections['broken'].error.message}", fg="yellow")
    elif broken:
        _render_rows(shown_broken)
        _note_truncation(len(shown_broken), len(broken), source_truncated=source_truncated["broken_tests"])
    else:
        suffix = " in returned rows" if source_truncated["broken_tests"] else ""
        click.echo(f"{'':<20}no match{suffix}")
        _note_truncation(0, 0, source_truncated=source_truncated["broken_tests"])
    click.echo("")
    click.secho(f"test health         ranked by blast radius, last {days} days", bold=True)
    if sections["flaky"].error is not None:
        click.secho(f"{'':<20}unavailable: {sections['flaky'].error.message}", fg="yellow")
    elif flaky:
        _render_flaky(shown_flaky)
        _note_truncation(len(shown_flaky), len(flaky), source_truncated=source_truncated["flaky_tests"])
    else:
        suffix = " in returned rows" if source_truncated["flaky_tests"] else ""
        click.echo(f"{'':<20}no match{suffix}")
        _note_truncation(0, 0, source_truncated=source_truncated["flaky_tests"])
    if not broken and not flaky and not errors:
        click.echo(
            "\nError signatures normalize volatile numbers and hashes. Search stable text or a test name.\n"
            "Only pytest error text from the last 2 days is searchable here; for older or non-pytest text, use\n"
            "the investigating-ci-failures skill's SQL over engineering_analytics_ci_failures."
        )
    raise SystemExit(0)


def _note_truncation(shown: int, total: int, *, source_truncated: bool) -> None:
    if shown < total:
        click.echo(f"{'':<20}Showing {shown} of {total}. Raise --limit, or 0 for every row.")
    if source_truncated:
        click.echo(f"{'':<20}Endpoint cap reached; more matches may exist.")


def _render_flaky(items: list[_FlakyTestItem]) -> None:
    click.echo(f"  {'CLASSIFICATION':<24}{'RUNS':>5}{'PRS':>5}{'MSTR':>6}  TEST")
    for item in items:
        click.echo(
            f"  {item['classification']:<24}{item['failed_run_count']:>5}"
            f"{item['failed_pr_count']:>5}{item['master_failed_run_count']:>6}  "
            f"{_short(item['selector'] or item['nodeid'], max(24, _term_width() - 46))}"
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
        row = _resolve_ref(api.broken_tests()["rows"], ref)
        # The endpoint writes `latest_run_id or 0`, so 0 is "no run id recorded" rather than a run.
        run_id = row["latest_run_id"]
        logs = api.run_failure_logs(run_id=run_id) if with_logs and run_id else None
    except _ApiError as exc:
        _fail(exc)
    if options.emits_json():
        _emit_json({**_summarize_row(row), "logs": logs})

    state = _terminal_text(row["state"])
    click.secho(f"{_ref(row['fingerprint'])}  {_terminal_text(row['test_id'])}", bold=True)
    click.echo(f"\n  {'state':<18}{state}: {_STATE_MEANINGS.get(state, 'unclassified')}")
    for label, value in (
        ("error", row["error_signature"]),
        ("job", row["job_name"]),
        ("repo", row["repo"]),
        ("occurrences", row["occurrences"]),
        ("branches", row["branches"]),
        ("master hits", row["master_hits"]),
        ("first seen", row["first_seen"]),
        ("last seen", row["last_seen"]),
        ("latest run", row["latest_run_id"]),
        ("latest branch", row["latest_branch"]),
    ):
        click.echo(f"  {label:<18}{_terminal_text(value)}")
    trend = row["trend_24h"]
    click.echo(f"  {'last 24h':<18}{_spark(trend)}  ({sum(trend)} failures, oldest hour first)")
    if with_logs:
        if not run_id:
            click.echo("\n  No failure logs: this failure has no run id recorded, so there is nothing to fetch.")
        else:
            if logs is not None:
                _render_logs(logs)
    click.echo(f"\n{_CAVEATS}")
    raise SystemExit(0)


def _render_logs(logs: _RunFailureLogs) -> None:
    """The thinned failure region per failed job. Jobs carry an id but no name, so the run
    id and branch are the only anchors back to GitHub."""
    if not logs["logs_available"]:
        click.echo("\n  No failure logs: the run did not fail, or its logs aged out of the short Logs retention.")
        return
    for job in logs["jobs"]:
        job_id = _terminal_text(job["job_id"])
        run_id = _terminal_text(job["run_id"])
        conclusion = _terminal_text(job["conclusion"])
        branch = _terminal_text(job["branch"])
        click.echo(f"\n  job {job_id} · run {run_id} · {conclusion} · {branch}")
        for line in job["lines"]:
            number = line["original_line"]
            text = _terminal_text(line["text"])
            click.echo(f"    {str(number) if number else '·':>7}  {text}")
        if job["truncated"]:
            # A run-level cap also sets this flag on the last job, so the exact cap is unknown.
            click.echo("    (job log output truncated)")
    if logs["truncated"]:
        click.echo("\n  Run log cap reached; later lines or jobs may be missing.")
