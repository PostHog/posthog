"""Decide whether migrations in a PR are safe enough to bypass the deny-list.

Reads the `Migration risk` GitHub check run posted on the head commit by CI.
That check is a generic CI feature — humans see it in the PR UI and any tool
that consumes check_runs can use it. Stamphog is one such consumer; nothing in
this module is specific to the analyzer's internals, only to the check's
public conclusion.

Conclusion semantics, defined by the analyzer (max risk level across all
migrations in the PR):
    success → all migrations Safe (brief or no lock, backwards compatible)
    neutral → at least one Needs Review (may have performance impact)
    failure → at least one Blocked (locks, breaks compatibility, or no rollback)

Race story: GitHub check runs are bound to a commit SHA at the API level —
`pr.check_runs` only returns checks attached to the current head commit, so a
stale check from an earlier commit can't be read here by construction. The
function falls back to "no info" (empty result → deny-list still fires) when
the check is missing, in-flight, or has any non-success conclusion.
"""

from pathlib import Path

CHECK_NAME = "Migration risk"


def safe_migration_files(check_runs: list[dict], pr_file_paths: list[str]) -> set[str]:
    """Return migration files (and their max_migration.txt) that may bypass the deny-list.

    Returns an empty set when the check is missing, in-flight, or didn't conclude
    `success`. The caller treats that as "deny-list applies normally."
    """
    if not _all_safe(check_runs):
        return set()

    safe: set[str] = set()
    for path in pr_file_paths:
        if _is_migration_file(path):
            safe.add(path)
            safe.add(str(Path(path).parent / "max_migration.txt"))
    return safe


def migration_check_pending(check_runs: list[dict], pr_file_paths: list[str]) -> bool:
    """True when the PR touches migrations and the analyzer's verdict isn't in yet.

    Distinguishes "CI hasn't classified yet" from "CI says don't bypass." Used by
    `is_waiting_for_migration_check` to drive the WAITING state.

    Returns False when there are no migration files in the PR (nothing to wait
    for), or when a `Migration risk` check has reached `status=completed`
    (verdict is in, even if not `success`).
    """
    if not any(_is_migration_file(p) for p in pr_file_paths):
        return False
    return _latest_completed(check_runs, CHECK_NAME) is None


def is_waiting_for_migration_check(
    deny_categories: list[str],
    non_deny_gate_failures: list[str],
    check_runs: list[dict],
    pr_file_paths: list[str],
) -> bool:
    """True when stamphog should hold off until the analyzer classifies the head.

    The WAITING state lets the bridge workflow auto-retrigger review when the
    Migration risk check completes — the stamphog label stays on, no verdict
    is posted, no LLM credit is burned.

    Conditions (all must hold):
      - `migrations` is the only deny-list category that fired (other denies
        like auth or crypto won't clear when the analyzer finishes)
      - no non-deny-list gates are failing (size, prerequisites — same reason)
      - the migration check is pending for the current head commit
    """
    if deny_categories != ["migrations"]:
        return False
    if non_deny_gate_failures:
        return False
    return migration_check_pending(check_runs, pr_file_paths)


def _all_safe(check_runs: list[dict]) -> bool:
    """True iff a completed `Migration risk` check exists with conclusion=success."""
    latest = _latest_completed(check_runs, CHECK_NAME)
    return latest is not None and latest.get("conclusion") == "success"


def _latest_completed(check_runs: list[dict], name: str) -> dict | None:
    """Pick the most recent completed run for `name`, tolerating duplicates from re-runs."""
    completed = [cr for cr in check_runs if cr.get("name") == name and cr.get("status") == "completed"]
    if not completed:
        return None
    return max(completed, key=lambda cr: cr.get("completed_at") or "")


def _is_migration_file(path: str) -> bool:
    p = Path(path)
    return p.suffix == ".py" and p.parent.name == "migrations" and p.name != "__init__.py"
