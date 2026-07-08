"""Schema and rules for ``.test_quarantine.json`` — THE quarantine contract.

This module is stdlib-only and runner-agnostic: it knows nothing about pytest
markers or CI. Runner adapters (``pytest_support``, a future jest adapter,
``.github/scripts/turbo-discover.js``) consume the contract below and
interpret selectors for their runner; they must not reimplement parsing,
date handling, or matching beyond what is documented here.

File format (repo root, sorted by ``id``, 4-space indent, trailing newline)::

    {
        "version": 1,
        "entries": [
            {
                "id": "posthog/api/test/test_foo.py::TestFoo::test_bar",
                "runner": "pytest",
                "reason": "Flaky ClickHouse ordering assertion",
                "owner": "@team-product-analytics",
                "issue": "https://github.com/PostHog/posthog/issues/12345",
                "added": "2026-06-10",
                "expires": "2026-06-24",
                "mode": "run"
            }
        ]
    }

Fields: ``runner`` defaults to ``"pytest"``; ``mode`` is ``"run"`` (default,
the test still executes but cannot fail the suite) or ``"skip"`` (for hangs,
import-time flakes, and state-polluters — the test is not executed at all);
``issue`` is optional; everything else is required. ``added``/``expires`` are
ISO dates, so they also compare correctly as plain strings (which is how the
JS reader compares them).

Selector grammar (``id``, pytest):

- exact nodeid: ``posthog/api/test/test_foo.py::TestFoo::test_bar``
- prefix: a directory (``posthog/api/test``), file (``.../test_foo.py``),
  class (``...::TestFoo``), or test function (``...::test_bar``) — matches
  everything underneath it, where "underneath" means the next character in
  the nodeid is a ``/``, ``::``, or ``[`` boundary (so a function selector
  covers its parameterized variants, and partial names never match)
- ``product:<dashed-name>``: everything under ``products/<name_with_underscores>/``

When several entries match the same test, the most specific (longest)
selector wins — so a narrow ``mode: skip`` entry overrides a broad
``mode: run`` one.

Nodeids are repo-root-relative in every PostHog pytest invocation (product
suites pass ``--rootdir ../..``), so one id format works everywhere.

Expiry: an entry is ACTIVE while ``today (UTC) <= expires``; past that it is
inert — not an error — and the test blocks CI normally again. ``check`` is
where staleness becomes a failure: entries expired for more than the grace
period must be removed, and ``expires - added`` may not exceed
``MAX_QUARANTINE_DAYS``.

Forward compatibility: readers warn on (and preserve) unknown entry fields,
tolerate entries for unknown runners (filtered out by ``active_entries``,
never an error), and treat an unrecognized top-level ``version`` as
"quarantine disabled". Breaking schema changes bump ``version``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_QUARANTINE_DAYS = 30
DEFAULT_GRACE_DAYS = 7
DEFAULT_RUNNER = "pytest"
MODES = ("run", "skip")

REPO_ROOT = Path(__file__).resolve().parents[4]
QUARANTINE_PATH = REPO_ROOT / ".test_quarantine.json"

_PRODUCT_SELECTOR_PREFIX = "product:"
_ENTRY_FIELDS = ("id", "runner", "reason", "owner", "issue", "added", "expires", "mode")


@dataclass(frozen=True)
class Entry:
    id: str
    added: date
    expires: date
    runner: str = DEFAULT_RUNNER
    reason: str = ""
    owner: str = ""
    issue: str = ""
    mode: str = "run"
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadResult:
    """Outcome of reading a quarantine file.

    ``errors`` are contract violations (malformed JSON, bad entry) — entries
    that could not be parsed are dropped, the rest are kept, so enforcement
    stays fail-open while ``check`` can still fail. ``warnings`` are
    forward-compatibility notices and are never fatal.
    """

    entries: list[Entry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


def today_utc() -> date:
    return datetime.now(UTC).date()


def load(path: Path = QUARANTINE_PATH) -> LoadResult:
    """Read a quarantine file. A missing file means quarantine is simply off."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return LoadResult()
    except OSError as exc:
        return LoadResult(errors=[f"could not read {path}: {exc}"])
    return parse(text)


def parse(text: str) -> LoadResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return LoadResult(errors=[f"invalid JSON: {exc}"])
    if not isinstance(data, dict):
        return LoadResult(errors=["top level must be an object"])
    if data.get("version") != SCHEMA_VERSION:
        return LoadResult(errors=[f"unsupported version {data.get('version')!r} (expected {SCHEMA_VERSION})"])
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        return LoadResult(errors=["'entries' must be a list"])

    result = LoadResult(extras={k: v for k, v in data.items() if k not in ("version", "entries")})
    for index, raw in enumerate(raw_entries):
        entry = _parse_entry(raw, index, result)
        if entry is not None:
            result.entries.append(entry)
    return result


def _parse_entry(raw: Any, index: int, result: LoadResult) -> Entry | None:
    label = f"entries[{index}]"
    if not isinstance(raw, dict):
        result.errors.append(f"{label}: must be an object")
        return None
    if isinstance(raw.get("id"), str) and raw["id"]:
        label = f"entries[{index}] ({raw['id']})"
    else:
        result.errors.append(f"{label}: 'id' must be a non-empty string")
        return None

    for key in ("reason", "owner", "issue", "runner", "mode"):
        if key in raw and not isinstance(raw[key], str):
            result.errors.append(f"{label}: '{key}' must be a string")
            return None
    mode = raw.get("mode", "run")
    if mode not in MODES:
        result.errors.append(f"{label}: 'mode' must be one of {MODES}, got {mode!r}")
        return None

    dates: dict[str, date] = {}
    for key in ("added", "expires"):
        try:
            dates[key] = date.fromisoformat(raw.get(key, ""))
        except (TypeError, ValueError):
            result.errors.append(f"{label}: '{key}' must be an ISO date (YYYY-MM-DD)")
            return None

    extras = {k: v for k, v in raw.items() if k not in _ENTRY_FIELDS}
    if extras:
        result.warnings.append(f"{label}: unknown fields {sorted(extras)} (kept for forward compatibility)")

    return Entry(
        id=raw["id"],
        added=dates["added"],
        expires=dates["expires"],
        runner=raw.get("runner", DEFAULT_RUNNER),
        reason=raw.get("reason", ""),
        owner=raw.get("owner", ""),
        issue=raw.get("issue", ""),
        mode=mode,
        extras=extras,
    )


def is_active(entry: Entry, today: date) -> bool:
    return today <= entry.expires


def active_entries(entries: list[Entry], runner: str, today: date) -> list[Entry]:
    """Unexpired entries for one runner — entries for other (or future,
    unknown) runners are silently excluded, never an error."""
    return [e for e in entries if e.runner == runner and is_active(e, today)]


def selector_matches(selector: str, test_id: str) -> bool:
    """Does ``selector`` cover ``test_id``? See the grammar in the module docstring."""
    if selector.startswith(_PRODUCT_SELECTOR_PREFIX):
        return test_id.startswith(product_path_prefix(selector))
    selector = selector.rstrip("/")
    return test_id == selector or test_id.startswith((f"{selector}/", f"{selector}::", f"{selector}["))


def product_path_prefix(selector: str) -> str:
    """``product:batch-exports`` → ``products/batch_exports/``."""
    name = selector[len(_PRODUCT_SELECTOR_PREFIX) :]
    return f"products/{name.replace('-', '_')}/"


def find_match(entries: list[Entry], test_id: str) -> Entry | None:
    """The most specific (longest) matching selector wins, so a narrow
    ``mode: skip`` entry can override a broad ``mode: run`` one. Ties keep
    file order (sorted by id)."""
    matches = [e for e in entries if selector_matches(e.id, test_id)]
    return max(matches, key=lambda e: len(_expanded_selector(e.id)), default=None)


def _expanded_selector(selector: str) -> str:
    return product_path_prefix(selector) if selector.startswith(_PRODUCT_SELECTOR_PREFIX) else selector


def render(entries: list[Entry], extras: dict[str, Any] | None = None) -> str:
    """Serialize to the canonical on-disk form: sorted by id, 4-space indent,
    trailing newline. Unknown fields captured at parse time are written back."""
    payload: dict[str, Any] = {"version": SCHEMA_VERSION, **(extras or {})}
    payload["entries"] = [_entry_to_dict(e) for e in sorted(entries, key=lambda e: (e.id, e.runner))]
    return json.dumps(payload, indent=4) + "\n"


def _entry_to_dict(entry: Entry) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": entry.id,
        "runner": entry.runner,
        "reason": entry.reason,
        "owner": entry.owner,
        **({"issue": entry.issue} if entry.issue else {}),
        "added": entry.added.isoformat(),
        "expires": entry.expires.isoformat(),
        "mode": entry.mode,
    }
    out.update(sorted(entry.extras.items()))
    return out


def validate_selector(selector: str, runner: str) -> str | None:
    """Selector validity for known runners; returns a violation message or None.

    Only pytest selectors have rules today; other runners' grammars belong to
    their future adapters and are not validated here.
    """
    if runner != DEFAULT_RUNNER:
        return None
    if selector.startswith(_PRODUCT_SELECTOR_PREFIX):
        name = selector[len(_PRODUCT_SELECTOR_PREFIX) :]
        if "_" in name:
            # turbo-discover compares dashed product names; the underscored
            # directory form would silently skip nothing there.
            return "use the dashed product name (e.g. 'batch-exports'), not the directory form"
        product_dir = REPO_ROOT / product_path_prefix(selector)
        if not product_dir.is_dir():
            return f"no directory {product_dir.relative_to(REPO_ROOT)} — is the product name right?"
        return None
    if selector.startswith("/") or selector.startswith("\\"):
        return "must be repo-root-relative, not absolute"
    if any(c.isspace() for c in selector):
        return "must not contain whitespace"
    return None


def check(result: LoadResult, today: date, grace_days: int = DEFAULT_GRACE_DAYS) -> tuple[list[str], list[str]]:
    """Lint a loaded quarantine file; returns (violations, warnings).

    Violations: load errors, duplicate ids, ``expires`` before ``added`` or
    more than ``MAX_QUARANTINE_DAYS`` after it, entries expired beyond the
    grace period, invalid selectors for known runners. Warnings: load
    warnings, entries for runners without an enforcement adapter, entries
    inside the expiry grace period.
    """
    violations = list(result.errors)
    warnings = list(result.warnings)

    seen: set[tuple[str, str]] = set()
    for entry in result.entries:
        label = f"entry '{entry.id}'"
        if (entry.id, entry.runner) in seen:
            violations.append(f"{label}: duplicate id for runner '{entry.runner}'")
        seen.add((entry.id, entry.runner))

        if entry.expires < entry.added:
            violations.append(f"{label}: expires {entry.expires} is before added {entry.added}")
        elif entry.expires - entry.added > timedelta(days=MAX_QUARANTINE_DAYS):
            violations.append(f"{label}: quarantine window exceeds {MAX_QUARANTINE_DAYS} days")

        expired_for = (today - entry.expires).days
        if expired_for > grace_days:
            violations.append(f"{label}: expired {expired_for} days ago (grace is {grace_days}) — remove or re-triage")
        elif expired_for > 0:
            days_left = grace_days - expired_for
            deadline = f"within {days_left} days" if days_left else "today — grace period ends"
            warnings.append(f"{label}: expired {expired_for} days ago — remove {deadline}")

        if entry.runner != DEFAULT_RUNNER:
            warnings.append(f"{label}: runner '{entry.runner}' has no enforcement adapter yet")
        selector_problem = validate_selector(entry.id, entry.runner)
        if selector_problem is not None:
            violations.append(f"{label}: {selector_problem}")

    return violations, warnings
