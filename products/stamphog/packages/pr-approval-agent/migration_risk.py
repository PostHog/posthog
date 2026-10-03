"""Decide whether migrations in a PR are safe enough to bypass the deny-list.

Reads the `Migration risk` GitHub check run posted on the head commit by CI.
That check is a generic CI feature — humans see it in the PR UI and any tool
that consumes check_runs can use it. Stamphog is one such consumer; nothing in
this module is specific to the analyzer's internals, only to the check's
public conclusion plus a small marker the analyzer embeds in the summary.

Conclusion semantics, defined by the analyzer (max risk level across all
migrations the analyzer covered):
    success → all classified migrations Safe (brief or no lock, backwards
              compatible) OR no Django migrations to analyze
    neutral → at least one Needs Review (may have performance impact)
    failure → at least one Blocked, or analyzer crashed

GitHub check runs are bound to a commit SHA at the API level — `pr.check_runs`
only returns checks attached to the current head commit, so a stale check from
an earlier commit can't be read here by construction.

Bypass scoping: the analyzer only covers Django migrations and embeds the
exact list of analyzed file paths in the summary as a `<!-- stamphog:v1 [...] -->`
marker. Stamphog scopes its bypass to the intersection of (analyzed paths) and
(PR diff). Files in directories that share the `migrations/` name but are
managed by other systems (ClickHouse, async migrations, RBAC scripts) never
appear in the analyzer's list and so always fall through to the deny-list.
"""

import re
import json
from pathlib import Path

CHECK_NAME = "Migration risk"

_MARKER_RE = re.compile(r"<!--\s*stamphog:v1\s+(\[[^\]]*\])\s*-->")


def safe_migration_files(check_runs: list[dict], pr_file_paths: list[str]) -> set[str]:
    """Return migration files (and their max_migration.txt) that may bypass the deny-list.

    Returns an empty set when the check is missing, in-flight, didn't conclude
    `success`, or has no marker (older check pre-rollout). The caller treats
    that as "deny-list applies normally."
    """
    latest = _latest_completed(check_runs, CHECK_NAME)
    if latest is None or latest.get("conclusion") != "success":
        return set()

    analyzed = _analyzed_paths_from_check(latest)
    if not analyzed:
        return set()

    pr_paths = set(pr_file_paths)
    safe = analyzed & pr_paths
    # Pair each analyzed migration with its sibling max_migration.txt — the
    # bumped marker file is part of the same logical change and would
    # otherwise still trigger the deny-list. Only siblings of analyzed files
    # are paired, so unrelated `migrations/` dirs (ClickHouse etc.) stay out.
    for path in list(safe):
        safe.add(str(Path(path).parent / "max_migration.txt"))
    return safe


def migration_check_pending(check_runs: list[dict], pr_file_paths: list[str]) -> bool:
    """True when the PR touches migration-shaped files and no completed check exists.

    With the always-publish workflow, a missing completed check means CI
    simply hasn't finished yet — the analyzer publishes a verdict for every
    PR, including PRs that touch only non-Django migration directories.
    The `_is_migration_file` heuristic still gates this so PRs that don't
    touch any migration-shaped file aren't held up.
    """
    if not any(_is_migration_file(p) for p in pr_file_paths):
        return False
    return _latest_completed(check_runs, CHECK_NAME) is None


def _analyzed_paths_from_check(check_run: dict) -> set[str]:
    """Parse the `<!-- stamphog:v1 [...] -->` marker out of the check's summary.

    The marker holds a JSON array of repo-relative file paths the analyzer
    classified. Returns an empty set when the marker is missing, malformed,
    or empty — every failure mode falls back to "no bypass," which is the
    safe default.
    """
    summary = (check_run.get("output") or {}).get("summary") or ""
    match = _MARKER_RE.search(summary)
    if not match:
        return set()
    try:
        paths = json.loads(match.group(1))
    except json.JSONDecodeError:
        return set()
    if not isinstance(paths, list):
        return set()
    return {p for p in paths if isinstance(p, str)}


def _latest_completed(check_runs: list[dict], name: str) -> dict | None:
    """Pick the most recent completed run for `name`, tolerating duplicates from re-runs."""
    completed = [cr for cr in check_runs if cr.get("name") == name and cr.get("status") == "completed"]
    if not completed:
        return None
    return max(completed, key=lambda cr: cr.get("completed_at") or "")


def _is_migration_file(path: str) -> bool:
    p = Path(path)
    return p.suffix == ".py" and p.parent.name == "migrations" and p.name != "__init__.py"
