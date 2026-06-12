"""Read side of a repo's checked-in ``.test_quarantine.json``.

The v1 schema contract lives with the hogli quarantine tooling
(``tools/hogli-commands/hogli_commands/quarantine/core.py``); product isolation
forbids importing tools code, so the minimal read-side parsing is reimplemented
here. Reading is fail-open to match the enforcement readers: malformed entries
are dropped into ``parse_errors`` and the rest kept; unknown entry fields only
warn; entries for runners without an enforcement adapter are kept (the UI shows
the runner).

Acquisition order: the server's own checkout in DEBUG (so the tab is live in
local dev), then the caller-supplied ``repo``, then the connected GitHub
source's most active repo over the last 30 days.
"""

import re
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.cache import cache

import requests

from posthog.hogql import ast

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import (
    QuarantineEntry,
    QuarantineFile,
    QuarantineLifecycle,
    QuarantineMode,
    QuarantineSelectorKind,
    RepoRef,
)
from products.engineering_analytics.backend.logic.queries import _curated

QUARANTINE_FILENAME = ".test_quarantine.json"

_SCHEMA_VERSION = 1
_DEFAULT_RUNNER = "pytest"
# Matches DEFAULT_GRACE_DAYS in the quarantine contract: an expired entry stays
# inert for this long before `quarantine check` makes its removal mandatory.
_GRACE_DAYS = 7
_EXPIRING_SOON_DAYS = 7
_ENTRY_FIELDS = ("id", "runner", "reason", "owner", "issue", "added", "expires", "mode")

# SSRF hardening: both halves of `owner/name` must look like a GitHub slug
# before they are interpolated into the fetch URL.
_REPO_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_FETCH_TIMEOUT_SECONDS = 3
_CACHE_TTL_SECONDS = 60

# Most urgent first; ties broken by soonest expiry, then id.
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


def build_quarantine(*, team: Team, repo: str | None = None) -> QuarantineFile:
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
        resolved = _most_active_repo(team)
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
    """Parse v1 quarantine JSON into sorted entries plus parse errors/warnings."""
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


def _most_active_repo(team: Team) -> tuple[str, str] | None:
    sql = _REPO_SELECT.replace("__RUNS_SOURCE__", _curated.run_source())
    response = _curated.run_query(
        sql,
        team=team,
        query_type="engineering_analytics.quarantine_repo",
        placeholders={"date_from": ast.Constant(value=datetime.now(UTC) - timedelta(days=30))},
    )
    if not response.results:
        return None
    owner, name = response.results[0]
    return str(owner), str(name)


def _fetch_quarantine_text(owner: str, name: str) -> tuple[str | None, str | None]:
    """Returns ``(text, error)``: the file text on 200, ``(None, None)`` on 404
    (no quarantine file is not an error), ``(None, message)`` on any other
    failure."""
    cache_key = f"engineering_analytics_quarantine:{owner}/{name}"
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return cached, None

    url = f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/{QUARANTINE_FILENAME}"
    try:
        response = requests.get(url, timeout=_FETCH_TIMEOUT_SECONDS)
    except requests.RequestException as err:
        return None, f"could not fetch {QUARANTINE_FILENAME} for {owner}/{name}: {err}"
    if response.status_code == 404:
        return None, None
    if response.status_code != 200:
        return None, f"could not fetch {QUARANTINE_FILENAME} for {owner}/{name}: HTTP {response.status_code}"
    cache.set(cache_key, response.text, _CACHE_TTL_SECONDS)
    return response.text, None


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
