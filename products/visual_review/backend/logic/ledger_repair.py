"""Bring the baseline ledger of a shadow-mode repo in line with its baseline file at every position.

In shadow mode the baseline file decides every gate, and the ledger is recorded next to it. A file
change that never reached the ledger (an approval from before recording started, one skipped
because the ledger lock was busy, a revert that edited the file) leaves the two apart from that
position on. A repair appends entries until the ledger equals the file at every position from 1 to
the newest resolved commit. It never changes or deletes an entry, so positions, landed approvals and
the records frozen on runs keep their meaning.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority

from ..db import WRITER_DB
from ..facade.contracts import BaselineLedgerRepair, BaselineLedgerRepairEntry
from ..facade.enums import BaselineEntrySource, BaselineMode
from ..models import BaselineCommit, BaselineEntry, Repo
from . import baselines, errors, github_api, ledger

# GitHub filters the commit list by committer date, which does not always grow along the branch.
# The margin lets in a commit after the seed whose date is a little older than the seed's.
_LISTING_MARGIN = timedelta(days=1)


@frozen
class _BaselineFileHistory:
    """The verified baseline file at the seed, and what changed at each ledger position whose commit changed it."""

    seed_sha: str
    cursor_position: int
    cursor_sha: str
    at_seed: dict[str, str]
    # Per position only the identifiers whose hash changed against the version before, with an
    # empty hash for a removed one, so the history does not hold a full copy of the file per change.
    changes: dict[int, dict[str, str]]
    # Read at the cursor commit itself, not derived from the list of changes, so a change the list
    # missed shows up as drift after the repair.
    at_cursor_commit: dict[str, str]
    unplaced_commits: tuple[str, ...]


@frozen
class _LedgerChange:
    identifier: str
    # Empty for a removal.
    content_hash: str


def _drift(ledger_hashes: dict[str, str], file_hashes: dict[str, str]) -> tuple[str, ...]:
    """The identifiers on which the two disagree. An empty hash and an absent identifier are the same."""
    return tuple(
        sorted(
            identifier
            for identifier in set(ledger_hashes) | set(file_hashes)
            if ledger_hashes.get(identifier, "") != file_hashes.get(identifier, "")
        )
    )


def _require_shadow_mode(repo: Repo) -> None:
    if repo.baseline_mode == BaselineMode.SHADOW:
        return
    if repo.baseline_mode == BaselineMode.LEDGER:
        raise errors.BaselineRepairError(
            f"{repo.repo_full_name} is in ledger mode, where the ledger decides and the baseline file "
            "follows it. Repair only runs in shadow mode, where the baseline file decides."
        )
    raise errors.BaselineRepairError(
        f"{repo.repo_full_name} is in {repo.baseline_mode} mode. Repair only runs in shadow mode."
    )


def _seed_commit(repo: Repo) -> BaselineCommit:
    seed = BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo.id, position=0).first()
    if seed is None:
        raise errors.BaselineRepairError(f"{repo.repo_full_name} has no baseline ledger.")
    return seed


def _newest_resolved_commit(repo: Repo) -> BaselineCommit:
    """The repair stops here, because an unresolved commit above it can still land an approval of its own."""
    commit = (
        BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo.id, resolved=True).order_by("-position").first()
    )
    if commit is None:
        raise errors.BaselineRepairError(f"{repo.repo_full_name} has no resolved ledger commit.")
    return commit


def _read_baseline_file_history(repo: Repo, run_type: str) -> _BaselineFileHistory:
    """Read the file from GitHub at the seed and at each commit that changed it, up to the newest resolved commit."""
    seed = _seed_commit(repo)
    cursor = _newest_resolved_commit(repo)
    path = baselines.baseline_file_path(repo, run_type)

    seed_date = github_api.commit_date(repo, seed.commit_sha, Priority.BATCH)
    if seed_date is None:
        raise errors.BaselineRepairError(f"GitHub did not return the seed commit {seed.commit_sha}.")
    listed = github_api.commits_touching_path(
        repo, path, cursor.commit_sha, since=seed_date - _LISTING_MARGIN, priority=Priority.BATCH
    )
    if listed is None:
        raise errors.BaselineRepairError(
            f"GitHub did not list the commits that changed {path} up to {cursor.commit_sha}."
        )

    positions = dict(
        BaselineCommit.objects.using(WRITER_DB)
        .filter(repo_id=repo.id, commit_sha__in=[commit.sha for commit in listed], position__lte=cursor.position)
        .values_list("commit_sha", "position")
    )
    # A commit of a branch that a merge commit brought in has no position. A commit from before the
    # seed has none either, and the margin of the listing lets some of those in, so they are left out.
    unplaced = tuple(
        commit.sha
        for commit in listed
        if commit.sha not in positions and (commit.committed_at is None or commit.committed_at >= seed_date)
    )

    github = github_api.get_github_integration_for_repo(repo, Priority.BATCH)
    at_seed = baselines._resolve_baselines_at_ref(repo, github, run_type, seed.commit_sha)
    changes: dict[int, dict[str, str]] = {}
    previous = at_seed
    for sha, position in sorted(positions.items(), key=lambda item: item[1]):
        if position == 0:
            continue
        current = baselines._resolve_baselines_at_ref(repo, github, run_type, sha)
        changes[position] = {identifier: current.get(identifier, "") for identifier in _drift(previous, current)}
        previous = current
    at_cursor_commit = previous
    if cursor.position not in changes:
        at_cursor_commit = baselines._resolve_baselines_at_ref(repo, github, run_type, cursor.commit_sha)
    return _BaselineFileHistory(
        seed_sha=seed.commit_sha,
        cursor_position=cursor.position,
        cursor_sha=cursor.commit_sha,
        at_seed=at_seed,
        changes=changes,
        at_cursor_commit=at_cursor_commit,
        unplaced_commits=unplaced,
    )


def _entries_by_position(repo: Repo, run_type: str, cursor_position: int) -> dict[int, list[_LedgerChange]]:
    """Each position's entries in insert order, so a later entry at one position wins."""
    rows = (
        BaselineEntry.objects.using(WRITER_DB)
        .filter(repo_id=repo.id, run_type=run_type, position__lte=cursor_position)
        .order_by("position", "id")
        .values_list("position", "identifier", "content_hash")
    )
    by_position: dict[int, list[_LedgerChange]] = {}
    for position, identifier, content_hash in rows:
        by_position.setdefault(position, []).append(_LedgerChange(identifier=identifier, content_hash=content_hash))
    return by_position


def _commits_at(repo: Repo, positions: Iterable[int]) -> dict[int, BaselineCommit]:
    return {
        commit.position: commit
        for commit in BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo.id, position__in=list(positions))
    }


def _plan(repo: Repo, run_type: str, history: _BaselineFileHistory) -> BaselineLedgerRepair:
    """Walk the positions where the ledger or the file changes, and append where the two differ.

    Between two such positions neither changes, so equality at each of them is equality everywhere.
    Position 1 is always checked, so a ledger seeded with another picture than the file is repaired
    at the first position after the seed. Each repair counts for the comparisons after it.
    """
    entries_by_position = _entries_by_position(repo, run_type, history.cursor_position)
    ledger_hashes = {change.identifier: change.content_hash for change in entries_by_position.get(0, [])}
    original_hashes = dict(ledger_hashes)
    file_hashes = dict(history.at_seed)

    positions = set(entries_by_position) | set(history.changes)
    if history.cursor_position >= 1:
        positions.add(1)
    positions.discard(0)
    commits = _commits_at(repo, positions)

    planned: list[BaselineLedgerRepairEntry] = []
    for position in sorted(positions):
        for change in entries_by_position.get(position, []):
            ledger_hashes[change.identifier] = change.content_hash
            original_hashes[change.identifier] = change.content_hash
        file_hashes.update(history.changes.get(position, {}))
        commit = commits[position]
        for identifier in _drift(ledger_hashes, file_hashes):
            planned.append(
                BaselineLedgerRepairEntry(
                    position=position,
                    commit_sha=commit.commit_sha,
                    pr_number=commit.pr_number,
                    identifier=identifier,
                    previous_hash=ledger_hashes.get(identifier, ""),
                    content_hash=file_hashes.get(identifier, ""),
                )
            )
            ledger_hashes[identifier] = file_hashes.get(identifier, "")

    return BaselineLedgerRepair(
        run_type=run_type,
        cursor_position=history.cursor_position,
        cursor_sha=history.cursor_sha,
        entries=tuple(planned),
        drift_before=_drift(original_hashes, history.at_cursor_commit),
        drift_after=_drift(ledger_hashes, history.at_cursor_commit),
        unplaced_commits=history.unplaced_commits,
    )


def _mismatches(repo: Repo, run_type: str, plan: BaselineLedgerRepair) -> tuple[str, ...]:
    """The planned entries whose hash differs from the file read at their own commit.

    The walk only knows the changes GitHub listed. A missed change that a later listed change undoes
    leaves no drift at the cursor, but the walk then repairs the positions in between against an
    older file. Reading the file at every repaired commit catches that.
    """
    github = github_api.get_github_integration_for_repo(repo, Priority.BATCH)
    entries_by_commit: dict[str, list[BaselineLedgerRepairEntry]] = {}
    for entry in plan.entries:
        entries_by_commit.setdefault(entry.commit_sha, []).append(entry)

    mismatches: list[str] = []
    for commit_sha, entries in entries_by_commit.items():
        file_hashes = baselines._resolve_baselines_at_ref(repo, github, run_type, commit_sha)
        for entry in entries:
            in_file = file_hashes.get(entry.identifier, "")
            if in_file == entry.content_hash:
                continue
            mismatches.append(
                f"position {entry.position}, {entry.identifier}: the plan has {entry.content_hash or 'removed'}, "
                f"the file at {commit_sha} has {in_file or 'nothing'}"
            )
    return tuple(mismatches)


@frozen
class _CheckedPlan:
    history: _BaselineFileHistory
    plan: BaselineLedgerRepair


def _read_and_plan(repo: Repo, run_type: str) -> _CheckedPlan:
    """Read GitHub, plan, and check the plan against the file at each repaired commit. Takes no lock."""
    try:
        history = _read_baseline_file_history(repo, run_type)
        plan = _plan(repo, run_type, history)
        return _CheckedPlan(history=history, plan=replace(plan, mismatches=_mismatches(repo, run_type, plan)))
    except github_api.GITHUB_READ_REFUSED as e:
        raise errors.BaselineRepairError(
            "GitHub or the egress budget refused a read of the baseline file history. Try again later."
        ) from e


def plan_repair(repo: Repo, run_type: str) -> BaselineLedgerRepair:
    """The entries a repair would append, without writing them. Raises `BaselineRepairError`."""
    _require_shadow_mode(repo)
    return _read_and_plan(repo, run_type).plan


def _refuse_unsafe(plan: BaselineLedgerRepair) -> None:
    """Refuse a plan that rests on an incomplete list of the file's changes."""
    if plan.mismatches:
        raise errors.BaselineRepairError(
            f"{len(plan.mismatches)} planned entries differ from the baseline file at their own commit, so "
            "GitHub's list of the file's changes is incomplete. Nothing was written. Run without --apply to see them."
        )
    if plan.drift_after:
        raise errors.BaselineRepairError(
            f"After the repair {len(plan.drift_after)} identifiers would still differ from the baseline file "
            f"at {plan.cursor_sha}, so GitHub's list of the file's changes is incomplete. Nothing was written."
        )


def _write(repo: Repo, plan: BaselineLedgerRepair) -> None:
    ledger.append_entries(
        [
            BaselineEntry(
                repo=repo,
                team_id=repo.team_id,
                run_type=plan.run_type,
                identifier=entry.identifier,
                content_hash=entry.content_hash,
                previous_hash=entry.previous_hash,
                position=entry.position,
                commit_sha=entry.commit_sha,
                source=BaselineEntrySource.REPAIR,
                pr_number=entry.pr_number,
            )
            for entry in plan.entries
        ]
    )


def apply_repair(repo: Repo, run_type: str) -> BaselineLedgerRepair:
    """Append the repair entries and return what was written, with the drift read back from the ledger.

    GitHub is read and the plan checked before the lock, so a slow GitHub never holds it. Under the
    lock the plan is made again from the entries as they are then. When it differs from the checked
    plan, an approval landed in between, and nothing is written. The repair stays at the commit the
    file was read up to, even when the cursor moved on.
    """
    _require_shadow_mode(repo)
    read = _read_and_plan(repo, run_type)
    history = read.history
    checked = read.plan
    _refuse_unsafe(checked)
    with transaction.atomic(using=WRITER_DB):
        ledger.lock_ledger(repo.id)
        repo.refresh_from_db(using=WRITER_DB, fields=["baseline_mode"])
        _require_shadow_mode(repo)
        if _seed_commit(repo).commit_sha != history.seed_sha:
            raise errors.BaselineRepairError(
                f"The ledger of {repo.repo_full_name} was seeded again during the repair. Run it again."
            )
        plan = _plan(repo, run_type, history)
        if plan.entries != checked.entries:
            raise errors.BaselineRepairError(
                f"The ledger of {repo.repo_full_name} changed while the baseline file was read. "
                "Nothing was written. Run the repair again."
            )
        _write(repo, plan)
        ledger_at_cursor = ledger.ledger_at(repo.id, run_type, history.cursor_position)
    return replace(checked, drift_after=_drift(ledger_at_cursor, history.at_cursor_commit))
