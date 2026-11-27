"""Read and write sides of a repo's checked-in ``.test_quarantine.json``.

The v1 schema contract lives with the hogli quarantine tooling
(``tools/hogli-commands/hogli_commands/quarantine/core.py``). Product isolation
forbids importing tools code, so the minimal parsing is reimplemented here.

Reading is fail-open to match the enforcement readers: a malformed entry goes to
``parse_errors`` and the rest are kept, and a team with no connected source gets
``available=false``. The file comes from the server's own checkout in DEBUG, then
the caller-supplied ``repo``, then the connected source's most active repo.

Writing is fail-closed: it refuses to edit a malformed file, and it renders the
file byte-for-byte the way ``core.render`` does.
"""

import re
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache

import requests
import structlog

from posthog.hogql import ast

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import (
    GitHubSourceNotConnectedError,
    QuarantineEntry,
    QuarantineFile,
    QuarantineLifecycle,
    QuarantineMode,
    QuarantineRequest,
    QuarantineRequestAction,
    QuarantineRequestResult,
    QuarantineRunner,
    QuarantineSelectorKind,
    QuarantineWriteError,
    RepoRef,
)
from products.engineering_analytics.backend.logic.queries import _curated
from products.engineering_analytics.backend.logic.sources import list_github_sources

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)

QUARANTINE_FILENAME = ".test_quarantine.json"

_SCHEMA_VERSION = 1
_DEFAULT_RUNNER = "pytest"
# Must match GRACE_DAYS in the hogli quarantine contract.
_GRACE_DAYS = 7
_EXPIRING_SOON_DAYS = 7
_ENTRY_FIELDS = ("id", "runner", "reason", "owner", "issue", "added", "expires", "mode")

# SSRF hardening: both halves of `owner/name` must look like a GitHub slug
# before they are interpolated into the fetch URL.
_REPO_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_FETCH_TIMEOUT_SECONDS = 3
_CACHE_TTL_SECONDS = 60
# Bounds how much a hostile public repo can make one request buffer, cache, and parse.
_MAX_QUARANTINE_BYTES = 5 * 1024 * 1024

_LIFECYCLE_URGENCY = {
    QuarantineLifecycle.OVERDUE: 0,
    QuarantineLifecycle.IN_GRACE: 1,
    QuarantineLifecycle.EXPIRING_SOON: 2,
    QuarantineLifecycle.ACTIVE: 3,
}

_REPO_SELECT = """
    SELECT repo_owner, repo_name
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {date_from}
    GROUP BY repo_owner, repo_name
    ORDER BY count() DESC
    LIMIT 1
"""


def build_quarantine(
    *,
    team: Team,
    repo: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> QuarantineFile:
    generated_at = datetime.now(UTC)
    today = generated_at.date()

    local_text = _read_local_text()
    if local_text is not None:
        entries, errors, warnings = parse_quarantine_text(local_text, today)
        return QuarantineFile(
            available=True,
            entries=entries,
            parse_errors=errors,
            parse_warnings=warnings,
            repo=None,
            source_url="",
            generated_at=generated_at,
        )

    if repo is not None:
        owner, _, name = repo.partition("/")
    else:
        try:
            resolved = _most_active_repo(team, source_id=source_id, user_access_control=user_access_control)
        except GitHubSourceNotConnectedError as exc:
            return _unavailable(generated_at, error=f"{exc} — pass ?repo=owner/name to read a specific repository")
        if resolved is None:
            return _unavailable(
                generated_at,
                error="could not determine a repository: no workflow runs in the last 30 days — pass ?repo=owner/name",
            )
        owner, name = resolved
    if not (_REPO_PART_RE.fullmatch(owner) and _REPO_PART_RE.fullmatch(name)):
        slug = repo if repo is not None else f"{owner}/{name}"
        return _unavailable(generated_at, error=f"invalid repo {slug!r}: expected 'owner/name' GitHub slugs")

    repo_ref = RepoRef(provider="github", owner=owner, name=name)
    text, fetch_error = _fetch_quarantine_text(owner, name)
    if text is None:
        return _unavailable(generated_at, repo=repo_ref, error=fetch_error)

    entries, errors, warnings = parse_quarantine_text(text, today)
    return QuarantineFile(
        available=True,
        entries=entries,
        parse_errors=errors,
        parse_warnings=warnings,
        repo=repo_ref,
        source_url=f"https://github.com/{owner}/{name}/blob/HEAD/{QUARANTINE_FILENAME}",
        generated_at=generated_at,
    )


def parse_quarantine_text(text: str, today: date) -> tuple[list[QuarantineEntry], list[str], list[str]]:
    """Return ``(entries, errors, warnings)``, with entries sorted most urgent first."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"invalid JSON: {exc}"], []
    if not isinstance(data, dict):
        return [], ["top level must be an object"], []
    if data.get("version") != _SCHEMA_VERSION:
        return [], [f"unsupported version {data.get('version')!r} (expected {_SCHEMA_VERSION})"], []
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        return [], ["'entries' must be a list"], []

    entries: list[QuarantineEntry] = []
    errors: list[str] = []
    warnings: list[str] = []
    for index, raw in enumerate(raw_entries):
        entry = _parse_entry(raw, index, today, errors, warnings)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: (_LIFECYCLE_URGENCY[entry.lifecycle], entry.expires, entry.id))
    return entries, errors, warnings


def _parse_entry(
    raw: object, index: int, today: date, errors: list[str], warnings: list[str]
) -> QuarantineEntry | None:
    label = f"entries[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{label}: must be an object")
        return None
    raw_id = raw.get("id")
    if not (isinstance(raw_id, str) and raw_id):
        errors.append(f"{label}: 'id' must be a non-empty string")
        return None
    label = f"entries[{index}] ({raw_id})"

    for key in ("reason", "owner", "issue", "runner", "mode"):
        if key in raw and not isinstance(raw[key], str):
            errors.append(f"{label}: '{key}' must be a string")
            return None
    mode = raw.get("mode", QuarantineMode.RUN.value)
    if mode not in (QuarantineMode.RUN.value, QuarantineMode.SKIP.value):
        errors.append(f"{label}: 'mode' must be one of ('run', 'skip'), got {mode!r}")
        return None

    dates: dict[str, date] = {}
    for key in ("added", "expires"):
        try:
            dates[key] = date.fromisoformat(raw.get(key, ""))
        except (TypeError, ValueError):
            errors.append(f"{label}: '{key}' must be an ISO date (YYYY-MM-DD)")
            return None

    unknown = sorted(key for key in raw if key not in _ENTRY_FIELDS)
    if unknown:
        warnings.append(f"{label}: unknown fields {unknown} (kept for forward compatibility)")

    days_until_expiry = (dates["expires"] - today).days
    return QuarantineEntry(
        id=raw_id,
        runner=raw.get("runner", _DEFAULT_RUNNER),
        reason=raw.get("reason", ""),
        owner=raw.get("owner", ""),
        issue=raw.get("issue", ""),
        added=dates["added"],
        expires=dates["expires"],
        mode=QuarantineMode(mode),
        lifecycle=_lifecycle_for(days_until_expiry),
        days_until_expiry=days_until_expiry,
        selector_kind=_selector_kind(raw_id),
    )


def _lifecycle_for(days_until_expiry: int) -> QuarantineLifecycle:
    if days_until_expiry > _EXPIRING_SOON_DAYS:
        return QuarantineLifecycle.ACTIVE
    if days_until_expiry >= 0:
        return QuarantineLifecycle.EXPIRING_SOON
    if days_until_expiry >= -_GRACE_DAYS:
        return QuarantineLifecycle.IN_GRACE
    return QuarantineLifecycle.OVERDUE


def _selector_kind(selector: str) -> QuarantineSelectorKind:
    if selector.startswith("product:"):
        return QuarantineSelectorKind.PRODUCT
    if "::" in selector:
        return QuarantineSelectorKind.TEST
    if PurePosixPath(selector).suffix:
        return QuarantineSelectorKind.FILE
    return QuarantineSelectorKind.DIRECTORY


def _read_local_text() -> str | None:
    if not settings.DEBUG:
        return None
    path = Path(settings.BASE_DIR) / QUARANTINE_FILENAME
    if not path.is_file():
        return None
    return path.read_text()


def _most_active_repo(
    team: Team, *, source_id: str | None = None, user_access_control: "UserAccessControl | None" = None
) -> tuple[str, str] | None:
    curated = _curated.CuratedGitHubSource.for_team(team, source_id=source_id, user_access_control=user_access_control)
    date_from = datetime.now(UTC) - timedelta(days=30)
    sql = _REPO_SELECT.replace("__RUNS_SOURCE__", curated.run_source(since=date_from))
    response = curated.run(
        sql,
        query_type="engineering_analytics.quarantine_repo",
        placeholders={"date_from": ast.Constant(value=date_from)},
    )
    if not response.results:
        return None
    owner, name = response.results[0]
    return str(owner), str(name)


def _repo_is_connected(
    team: Team,
    owner: str,
    name: str,
    *,
    user_access_control: "UserAccessControl | None" = None,
) -> bool:
    target = f"{owner}/{name}".lower()
    return any(
        source.repo.lower() == target
        for source in list_github_sources(team=team, user_access_control=user_access_control)
    )


def _fetch_quarantine_text(owner: str, name: str) -> tuple[str | None, str | None]:
    """Return ``(text, error)``. A 404 returns ``(None, None)``, because a repo with no
    quarantine file is not an error. Any other failure returns ``(None, message)``."""
    cache_key = f"engineering_analytics_quarantine:{owner}/{name}"
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return cached, None

    url = f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/{QUARANTINE_FILENAME}"
    too_large = f"{QUARANTINE_FILENAME} for {owner}/{name} exceeds the {_MAX_QUARANTINE_BYTES}-byte limit"
    try:
        with requests.get(url, timeout=_FETCH_TIMEOUT_SECONDS, stream=True) as response:
            if response.status_code == 404:
                return None, None
            if response.status_code != 200:
                return None, f"could not fetch {QUARANTINE_FILENAME} for {owner}/{name}: HTTP {response.status_code}"
            # Content-Length can be absent or wrong, so the streamed read below is the actual ceiling.
            declared = response.headers.get("Content-Length")
            if declared is not None and declared.isdigit() and int(declared) > _MAX_QUARANTINE_BYTES:
                return None, too_large
            body = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                body.extend(chunk)
                if len(body) > _MAX_QUARANTINE_BYTES:
                    return None, too_large
    except requests.RequestException as err:
        return None, f"could not fetch {QUARANTINE_FILENAME} for {owner}/{name}: {err}"

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None, f"could not fetch {QUARANTINE_FILENAME} for {owner}/{name}: not valid UTF-8"
    cache.set(cache_key, text, _CACHE_TTL_SECONDS)
    return text, None


def _unavailable(generated_at: datetime, *, repo: RepoRef | None = None, error: str | None = None) -> QuarantineFile:
    return QuarantineFile(
        available=False,
        entries=[],
        parse_errors=[error] if error else [],
        parse_warnings=[],
        repo=repo,
        source_url="",
        generated_at=generated_at,
    )


# Must match core.MAX_QUARANTINE_DAYS and the `add --days` default of the hogli CLI,
# so a PR opened here passes the same `quarantine check`.
_MAX_QUARANTINE_DAYS = 30
_DEFAULT_QUARANTINE_DAYS = 14


def request_quarantine(
    *,
    team: Team,
    request: QuarantineRequest,
    user_access_control: "UserAccessControl | None" = None,
) -> QuarantineRequestResult:
    """Open a PR (and, for a new quarantine, a tracking issue) that edits the repo's
    ``.test_quarantine.json``. Every failure raises ``QuarantineWriteError`` with a
    user-safe message."""
    selector = request.selector.strip()
    if not selector:
        raise QuarantineWriteError("A test selector is required.")

    try:
        return _open_quarantine_pr(
            team=team,
            selector=selector,
            request=request,
            user_access_control=user_access_control,
        )
    except QuarantineWriteError:
        raise
    except Exception as exc:
        # The GitHub integration calls raise plain Exception, ValueError, KeyError and
        # GitHubIntegrationError. The view renders only QuarantineWriteError as a 400,
        # so anything else would be a 500.
        logger.warning("quarantine_write_failed", team_id=team.pk, exc_info=exc)
        raise QuarantineWriteError(
            "Couldn't open the quarantine pull request — GitHub returned an unexpected error. "
            "The App may have lost access to the repository; check its installation and try again."
        ) from exc


def _open_quarantine_pr(
    *,
    team: Team,
    selector: str,
    request: QuarantineRequest,
    user_access_control: "UserAccessControl | None" = None,
) -> QuarantineRequestResult:
    github, owner, name = _resolve_write_target(team, request.repo, user_access_control=user_access_control)
    default_branch = github.get_default_branch(name)
    current = github.get_file_contents(name, QUARANTINE_FILENAME, ref=default_branch)
    entries, extras = _load_writable(current["content"] if current else None)

    if request.operation == QuarantineRequestAction.REMOVE:
        remaining = _remove_entry(entries, selector)
        if len(remaining) == len(entries):
            raise QuarantineWriteError(f"'{selector}' is not quarantined — nothing to remove.")
        new_entries, issue_url = remaining, ""
        commit_message = f"chore(ci): unquarantine {selector}"
        pr_body = _remove_pr_body(selector, request)
    else:
        runner = _resolve_request_runner(request, selector, entries)
        today = datetime.now(UTC).date()
        expires = request.expires or today + timedelta(days=_DEFAULT_QUARANTINE_DAYS)
        _validate_quarantine_inputs(request, today=today, expires=expires)

        if request.operation == QuarantineRequestAction.QUARANTINE:
            issue_url = _open_tracking_issue(github, name, owner, selector, request, expires)
        else:
            issue_url = request.issue

        new_entry = _canonical_entry(
            {
                "id": selector,
                "runner": runner.value,
                "reason": request.reason.strip(),
                "owner": request.owner.strip(),
                "issue": issue_url,
                "added": today.isoformat(),
                "expires": expires.isoformat(),
                "mode": request.mode.value,
            }
        )
        new_entries = _upsert_entry(entries, new_entry)
        verb = "quarantine" if request.operation == QuarantineRequestAction.QUARANTINE else "extend quarantine for"
        commit_message = f"chore(ci): {verb} {selector}"
        pr_body = _quarantine_pr_body(selector, request, expires, issue_url)

    content = render_quarantine_file(new_entries, extras)
    branch = _branch_for(request.operation, selector)
    pr_url = _commit_and_open_pr(
        github,
        name,
        default_branch=default_branch,
        branch=branch,
        content=content,
        commit_message=commit_message,
        pr_title=commit_message,
        pr_body=pr_body,
    )
    filed_issue_url = issue_url if request.operation == QuarantineRequestAction.QUARANTINE else ""
    return QuarantineRequestResult(pr_url=pr_url, issue_url=filed_issue_url, branch=branch)


def _validate_quarantine_inputs(request: QuarantineRequest, *, today: date, expires: date) -> None:
    if expires <= today:
        raise QuarantineWriteError("The expiry date must be in the future.")
    max_expiry = today + timedelta(days=_MAX_QUARANTINE_DAYS)
    if expires > max_expiry:
        raise QuarantineWriteError(
            f"A quarantine can last at most {_MAX_QUARANTINE_DAYS} days (until {max_expiry.isoformat()})."
        )
    if not request.reason.strip():
        raise QuarantineWriteError("A reason is required to quarantine a test.")
    if not request.owner.strip():
        raise QuarantineWriteError("An owning team or person is required.")


def _resolve_write_target(
    team: Team,
    repo: str | None,
    *,
    user_access_control: "UserAccessControl | None" = None,
) -> tuple[GitHubIntegration, str, str]:
    if repo is not None:
        owner, _, name = repo.partition("/")
    else:
        resolved = _most_active_repo(team, user_access_control=user_access_control)
        if resolved is None:
            raise QuarantineWriteError(
                "Couldn't tell which repository to quarantine in — no workflow runs in the last 30 days. "
                "Pass an explicit owner/name."
            )
        owner, name = resolved
    if not (_REPO_PART_RE.fullmatch(owner) and _REPO_PART_RE.fullmatch(name)):
        raise QuarantineWriteError(
            f"Invalid repository {(repo or f'{owner}/{name}')!r}: expected an 'owner/name' slug."
        )
    # An explicit repo is client-controlled, and the org check below only proves the App is
    # installed on that org. Without this gate a caller could aim the App's write token at
    # any repo in that org.
    if repo is not None and not _repo_is_connected(team, owner, name, user_access_control=user_access_control):
        raise QuarantineWriteError(
            f"'{owner}/{name}' isn't one of this team's connected GitHub repositories — "
            "connect it as a GitHub source to quarantine there."
        )

    integration_row = IntegrationManager.github.oauth.find(team.id)
    if integration_row is None:
        raise QuarantineWriteError("Connect a GitHub integration with write access to quarantine tests from here.")
    github = GitHubIntegration(integration_row, source="ci_quarantine", priority=Priority.CRITICAL)
    installed_org = github.organization()
    if installed_org.lower() != owner.lower():
        raise QuarantineWriteError(
            f"The connected GitHub App is installed on '{installed_org}', not '{owner}'. "
            f"Install it on {owner}/{name} to quarantine there."
        )
    return github, owner, name


def _open_tracking_issue(
    github: GitHubIntegration, repository: str, owner: str, selector: str, request: QuarantineRequest, expires: date
) -> str:
    result = github.create_issue(
        {
            "title": f"Flaky test quarantined: {selector}",
            "body": _issue_body(selector, request, expires),
            "repository": repository,
        }
    )
    return f"https://github.com/{owner}/{repository}/issues/{result['number']}"


def _commit_and_open_pr(
    github: GitHubIntegration,
    repository: str,
    *,
    default_branch: str,
    branch: str,
    content: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
) -> str:
    branch_result = github.create_branch(repository, branch, default_branch)
    if not branch_result.get("success"):
        raise QuarantineWriteError(f"Couldn't create the quarantine branch: {branch_result.get('error', 'unknown')}")
    update_result = github.update_file(repository, QUARANTINE_FILENAME, content, commit_message, branch)
    if not update_result.get("success"):
        raise QuarantineWriteError(f"Couldn't commit the quarantine change: {update_result.get('error', 'unknown')}")
    pr_result = github.create_pull_request(repository, pr_title, pr_body, branch, default_branch)
    if not pr_result.get("success"):
        raise QuarantineWriteError(f"Couldn't open the quarantine PR: {pr_result.get('error', 'unknown')}")
    return pr_result["pr_url"]


def _branch_for(action: QuarantineRequestAction, selector: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", selector).strip("-")[:60] or "test"
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    prefix = "unquarantine" if action == QuarantineRequestAction.REMOVE else "quarantine"
    return f"{prefix}/{slug}-{stamp}"


def _load_writable(text: str | None) -> tuple[list[dict], dict]:
    """Return the entry dicts and the top-level extras. A malformed file raises, so a
    write never drops a sibling entry."""
    if text is None:
        return [], {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QuarantineWriteError(f"The quarantine file isn't valid JSON ({exc}); fix it before editing here.")
    if not isinstance(data, dict) or data.get("version") != _SCHEMA_VERSION:
        raise QuarantineWriteError("The quarantine file is malformed or an unsupported version; fix it before editing.")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise QuarantineWriteError("The quarantine file's 'entries' must be a list; fix it before editing.")
    extras = {k: v for k, v in data.items() if k not in ("version", "entries")}
    return [_canonical_entry(raw) for raw in raw_entries], extras


def _canonical_entry(raw: object) -> dict:
    """Re-key one entry into the on-disk order ``core._entry_to_dict`` uses, so the
    output matches the CLI byte-for-byte."""
    if not isinstance(raw, dict):
        raise QuarantineWriteError("The quarantine file has a non-object entry; fix it before editing.")
    try:
        out = {
            "id": raw["id"],
            "runner": raw.get("runner", _DEFAULT_RUNNER),
            "reason": raw.get("reason", ""),
            "owner": raw.get("owner", ""),
            **({"issue": raw["issue"]} if raw.get("issue") else {}),
            "added": date.fromisoformat(raw["added"]).isoformat(),
            "expires": date.fromisoformat(raw["expires"]).isoformat(),
            "mode": raw.get("mode", QuarantineMode.RUN.value),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise QuarantineWriteError(
            f"The quarantine file has a malformed entry ({raw.get('id', '?')}); fix it before editing."
        ) from exc
    out.update(sorted((k, v) for k, v in raw.items() if k not in _ENTRY_FIELDS))
    return out


def _upsert_entry(entries: list[dict], new_entry: dict) -> list[dict]:
    key = (new_entry["id"], new_entry["runner"])
    return [e for e in entries if (e["id"], e["runner"]) != key] + [new_entry]


def _resolve_request_runner(request: QuarantineRequest, selector: str, entries: list[dict]) -> QuarantineRunner:
    """A request without a runner takes the runner of the selector's one existing entry,
    and raises when entries for several runners exist."""
    if request.runner is not None:
        return request.runner
    matching_runners = {entry["runner"] for entry in entries if entry["id"] == selector}
    if len(matching_runners) == 1:
        try:
            return QuarantineRunner(next(iter(matching_runners)))
        except ValueError as exc:
            raise QuarantineWriteError(
                f"'{selector}' uses an unsupported runner; update it in the quarantine file."
            ) from exc
    if matching_runners:
        raise QuarantineWriteError(f"'{selector}' is quarantined for multiple runners; specify which runner.")
    test_file = selector.partition("::")[0]
    if PurePosixPath(test_file).suffix in (".js", ".jsx", ".ts", ".tsx"):
        return QuarantineRunner.JEST
    return QuarantineRunner.PYTEST


def _remove_entry(entries: list[dict], selector: str) -> list[dict]:
    # Drops the selector for every runner, to match the CLI's `remove`.
    return [e for e in entries if e["id"] != selector]


def render_quarantine_file(entries: list[dict], extras: dict) -> str:
    """Must stay byte-identical to ``core.render``. The golden test in
    ``test_quarantine.py`` checks it."""
    payload: dict = {"version": _SCHEMA_VERSION, **extras}
    payload["entries"] = sorted(entries, key=lambda e: (e["id"], e["runner"]))
    return json.dumps(payload, indent=4) + "\n"


_GATE_FRESHNESS_NOTE = (
    "Note: a quarantine only affects CI runs that start after this PR merges; runs already in flight are unaffected."
)


def _issue_body(selector: str, request: QuarantineRequest, expires: date) -> str:
    mode_line = (
        "runs, but tolerated failures do not fail the suite"
        if request.mode == QuarantineMode.RUN
        else "is skipped entirely (not collected)"
    )
    return "\n".join(
        [
            f"`{selector}` was quarantined because it is flaky.",
            "",
            f"- **Owner:** {request.owner.strip() or '_unassigned_'}",
            f"- **Reason:** {request.reason.strip() or '_none given_'}",
            f"- **Mode:** the test {mode_line}.",
            f"- **Expires:** {expires.isoformat()} — after which it blocks CI again unless the quarantine is extended.",
            "",
            "Keep this issue open until the test is fixed and its quarantine entry removed; "
            "this is the durable record of the flake, not the quarantine PR.",
            "",
            _GATE_FRESHNESS_NOTE,
        ]
    )


def _quarantine_pr_body(selector: str, request: QuarantineRequest, expires: date, issue_url: str) -> str:
    verb = "Quarantines" if request.operation == QuarantineRequestAction.QUARANTINE else "Extends the quarantine for"
    lines = [
        f"{verb} the flaky test `{selector}` in `{QUARANTINE_FILENAME}` until {expires.isoformat()}.",
        "",
        f"- **Reason:** {request.reason.strip()}",
        f"- **Owner:** {request.owner.strip()}",
    ]
    if issue_url:
        # "Tracked in" and not "Closes", because the issue must stay open until the test is fixed.
        lines.append(f"- **Tracked in:** {issue_url}")
    lines += ["", _GATE_FRESHNESS_NOTE]
    return "\n".join(lines)


def _remove_pr_body(selector: str, request: QuarantineRequest) -> str:
    lines = [f"Removes `{selector}` from `{QUARANTINE_FILENAME}` so it gates CI normally again."]
    if request.issue:
        lines += ["", f"- **Tracking issue:** {request.issue}"]
    lines += ["", _GATE_FRESHNESS_NOTE]
    return "\n".join(lines)
