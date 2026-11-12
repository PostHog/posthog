"""The baseline ledger: an append-only record of approved baselines per repo and run type.

Each entry belongs to a position on the default branch's first-parent line. The ledger at a
position holds, per identifier, the newest entry at or below that position. A run reads the
ledger at its merge-base's position, the way git reads the baseline file in the merge-base's tree.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import connections, transaction

from ..db import WRITER_DB
from ..facade.enums import BaselineEntrySource, BaselineMode
from ..models import BaselineApproval, BaselineCommit, BaselineEntry, Repo
from . import errors

SEED_BATCH_SIZE = 1000


def _lock_key(repo_id: UUID) -> str:
    return f"visual-review-baseline-ledger:{repo_id}"


def lock_ledger(repo_id: UUID) -> None:
    """Serialize writes to one repo's ledger, commits and approvals until the transaction ends.

    Take it as the first lock of the transaction, before any row lock. `advance` holds it while
    its inserts take a share lock on the repo row, so a caller that locks a run (and with it the
    repo row) before this lock can deadlock with `advance`.

    The lock is transaction-scoped, so outside a transaction it would be released at once and
    protect nothing. That is why it refuses to run there.
    """
    if not connections[WRITER_DB].in_atomic_block:
        raise RuntimeError("lock_ledger needs a transaction on the visual review writer database")
    with connections[WRITER_DB].cursor() as db_cursor:
        db_cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [_lock_key(repo_id)])


def try_lock_ledger(repo_id: UUID) -> bool:
    """Take the ledger lock only when it is free, and say whether this transaction holds it now.

    For a caller that must never wait on the ledger. Like `lock_ledger`, it is the first lock of
    the transaction, and a caller that did not get it must not take it later.
    """
    if not connections[WRITER_DB].in_atomic_block:
        raise RuntimeError("try_lock_ledger needs a transaction on the visual review writer database")
    with connections[WRITER_DB].cursor() as db_cursor:
        db_cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", [_lock_key(repo_id)])
        return bool(db_cursor.fetchone()[0])


def cursor(repo_id: UUID) -> BaselineCommit | None:
    """The newest commit the ledger knows, or None when the repo has no ledger."""
    return BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo_id).order_by("-position").first()


def position_of(repo_id: UUID, commit_sha: str) -> int | None:
    return (
        BaselineCommit.objects.using(WRITER_DB)
        .filter(repo_id=repo_id, commit_sha=commit_sha)
        .values_list("position", flat=True)
        .first()
    )


def _hashes_at(repo_id: UUID, run_type: str, position: int, identifiers: Iterable[str] | None) -> dict[str, str]:
    entries = BaselineEntry.objects.using(WRITER_DB).filter(repo_id=repo_id, run_type=run_type, position__lte=position)
    if identifiers is not None:
        entries = entries.filter(identifier__in=list(identifiers))
    # The id breaks a tie on one position, because it grows in insert order.
    latest = entries.order_by("identifier", "-position", "-id").distinct("identifier")
    return {
        identifier: content_hash
        for identifier, content_hash in latest.values_list("identifier", "content_hash")
        if content_hash
    }


def ledger_at(repo_id: UUID, run_type: str, position: int) -> dict[str, str]:
    """The ledger at a position, as identifier to hash. A removed identifier is absent."""
    return _hashes_at(repo_id, run_type, position, None)


def hashes_at(repo_id: UUID, run_type: str, identifiers: Iterable[str], position: int) -> dict[str, str]:
    """The ledger at a position for these identifiers only. Absent and removed ones are left out."""
    return _hashes_at(repo_id, run_type, position, identifiers)


def identifiers_with_newer_entries(repo_id: UUID, run_type: str, identifiers: Iterable[str], position: int) -> set[str]:
    """Which of these identifiers have an entry above the position."""
    return set(
        BaselineEntry.objects.using(WRITER_DB)
        .filter(repo_id=repo_id, run_type=run_type, identifier__in=list(identifiers), position__gt=position)
        .values_list("identifier", flat=True)
        .distinct()
    )


def append_commit(
    repo: Repo, *, position: int, commit_sha: str, pr_number: int | None = None, resolved: bool = True
) -> BaselineCommit:
    """Insert one commit. The caller holds `lock_ledger`."""
    return BaselineCommit.objects.using(WRITER_DB).create(
        repo=repo,
        team_id=repo.team_id,
        position=position,
        commit_sha=commit_sha,
        pr_number=pr_number,
        resolved=resolved,
    )


def append_entry(
    repo: Repo,
    *,
    run_type: str,
    identifier: str,
    content_hash: str,
    previous_hash: str,
    position: int,
    commit_sha: str,
    source: BaselineEntrySource,
    approval: BaselineApproval | None = None,
    pr_number: int | None = None,
) -> BaselineEntry:
    """Insert one entry. The caller holds `lock_ledger`, which keeps ids in insert order."""
    return BaselineEntry.objects.using(WRITER_DB).create(
        repo=repo,
        team_id=repo.team_id,
        run_type=run_type,
        identifier=identifier,
        content_hash=content_hash,
        previous_hash=previous_hash,
        position=position,
        commit_sha=commit_sha,
        source=source,
        approval=approval,
        pr_number=pr_number,
    )


def append_entries(entries: list[BaselineEntry]) -> None:
    """Insert entries in list order. The caller holds `lock_ledger`, which keeps ids in insert order."""
    BaselineEntry.objects.using(WRITER_DB).bulk_create(entries)


def _delete_ledger(repo: Repo) -> None:
    BaselineEntry.objects.using(WRITER_DB).filter(repo_id=repo.id).delete()
    BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo.id).delete()


def _write_seed(repo: Repo, commit_sha: str, baselines_by_run_type: dict[str, dict[str, str]]) -> int:
    append_commit(repo, position=0, commit_sha=commit_sha)
    entries = [
        BaselineEntry(
            repo=repo,
            team_id=repo.team_id,
            run_type=run_type,
            identifier=identifier,
            content_hash=content_hash,
            position=0,
            commit_sha=commit_sha,
            source=BaselineEntrySource.SEED,
        )
        for run_type, baselines in sorted(baselines_by_run_type.items())
        for identifier, content_hash in sorted(baselines.items())
    ]
    BaselineEntry.objects.using(WRITER_DB).bulk_create(entries, batch_size=SEED_BATCH_SIZE)
    return len(entries)


def seed(
    repo: Repo, commit_sha: str, baselines_by_run_type: dict[str, dict[str, str]], *, replace: bool = False
) -> int:
    """Start the ledger at position 0 for `commit_sha`, with one entry per identifier.

    Returns the number of entries written. `replace` deletes the existing commits and entries
    first. Approvals stay, because they record what reviewers decided and the ledger does not.
    """
    with transaction.atomic(using=WRITER_DB):
        lock_ledger(repo.id)
        if cursor(repo.id) is not None:
            if not replace:
                raise errors.BaselineLedgerExistsError(
                    f"{repo.repo_full_name} already has a baseline ledger. Seed with replace to start it again."
                )
            _delete_ledger(repo)
        return _write_seed(repo, commit_sha, baselines_by_run_type)


def seed_from_ledger(repo: Repo, commit_sha: str) -> int:
    """Start the ledger again at position 0 for `commit_sha`, holding the ledger at the cursor.

    Removed identifiers are not carried, so the new ledger has no removal entries.
    Returns the number of entries written.
    """
    with transaction.atomic(using=WRITER_DB):
        lock_ledger(repo.id)
        head = cursor(repo.id)
        if head is None:
            raise errors.BaselineLedgerMissingError(f"{repo.repo_full_name} has no baseline ledger to seed from.")
        run_types = (
            BaselineEntry.objects.using(WRITER_DB)
            .filter(repo_id=repo.id)
            .order_by("run_type")
            .values_list("run_type", flat=True)
            .distinct()
        )
        baselines_by_run_type = {run_type: ledger_at(repo.id, run_type, head.position) for run_type in run_types}
        _delete_ledger(repo)
        return _write_seed(repo, commit_sha, baselines_by_run_type)


def set_baseline_mode(repo: Repo, mode: BaselineMode) -> None:
    """Change which record decides the repo's runs.

    Shadow and ledger mode need a seeded ledger first, because a run in either mode reads the
    ledger at its merge-base, and an empty ledger calls every story new.
    """
    with transaction.atomic(using=WRITER_DB):
        lock_ledger(repo.id)
        repo.refresh_from_db(using=WRITER_DB, fields=["commit_status_gate_enabled"])
        if mode != BaselineMode.YAML and cursor(repo.id) is None:
            raise errors.BaselineLedgerMissingError(
                f"{repo.repo_full_name} has no baseline ledger. Run the seed subcommand before setting {mode}."
            )
        if mode == BaselineMode.LEDGER and not repo.commit_status_gate_enabled:
            raise errors.CommitStatusGateError(
                f"{repo.repo_full_name} needs the commit status gate before ledger mode, because in ledger mode "
                "that status is the merge gate. Turn it on with the status-gate subcommand first."
            )
        repo.baseline_mode = mode
        repo.save(update_fields=["baseline_mode", "updated_at"])


def set_commit_status_gate(repo: Repo, enabled: bool) -> None:
    """Turn the status rules of the baseline ledger on or off for the repo's commit statuses.

    Under the ledger lock, so it cannot race a mode change. Ledger mode keeps it on, because there
    the status is the only gate of a run.
    """
    with transaction.atomic(using=WRITER_DB):
        lock_ledger(repo.id)
        repo.refresh_from_db(using=WRITER_DB, fields=["baseline_mode"])
        if not enabled and repo.baseline_mode == BaselineMode.LEDGER:
            raise errors.CommitStatusGateError(
                f"{repo.repo_full_name} is in ledger mode, where the commit status is the merge gate. "
                "Set the mode to shadow first."
            )
        repo.commit_status_gate_enabled = enabled
        repo.save(update_fields=["commit_status_gate_enabled", "updated_at"])
