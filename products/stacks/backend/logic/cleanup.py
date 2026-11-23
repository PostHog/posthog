"""Housekeeping: close runs that never finished, drop saved bytes nobody can push, sweep engine work
directories, and delete a project's stack data when the project goes."""

from __future__ import annotations

import time
import shutil
from collections.abc import Callable, Iterable

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.models.team.team import Team

from .. import engine_adapter
from ..db import WRITER_DB, database_ready
from ..facade.enums import DiffStatus
from ..models import Stack, StackBinding, StackDiff, StackNaturalClaim, StackRecordVersion, StackSecret
from . import lease, managed
from .stacks import empty_diff

logger = structlog.get_logger(__name__)

# Older than any run can be: the engine's own timeout plus the activity's margin. A hard-killed run can leave its
# record, its saved diff and a secrets file in its directory.
WORKDIR_MAX_AGE_SECONDS = 60 * 60


def timed_out_error() -> dict:
    return {"code": "run_timed_out", "message": "The diff did not finish in time. Run diff again."}


def sweep_workdir() -> int:
    """Remove engine work directories older than any run. Each worker sweeps its own disk before a run."""
    root = engine_adapter.workdir()
    if not root.is_dir():
        return 0
    cutoff = time.time() - WORKDIR_MAX_AGE_SECONDS
    removed = 0
    for entry in root.iterdir():
        try:
            if entry.is_dir() and not entry.is_symlink() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            logger.warning("stacks_workdir_sweep_failed", path=str(entry))
    return removed


def close_timed_out_diffs() -> int:
    return (
        StackDiff.all_teams.using(WRITER_DB)
        .filter(status=DiffStatus.RUNNING.value, deadline_at__lt=timezone.now())
        .update(
            status=DiffStatus.FAILED.value,
            diff=empty_diff([timed_out_error()]),
            encrypted_saved_diff=None,
        )
    )


def clear_expired_saved_diffs() -> int:
    return (
        StackDiff.all_teams.using(WRITER_DB)
        .filter(encrypted_saved_diff__isnull=False, expires_at__lt=timezone.now())
        .update(encrypted_saved_diff=None)
    )


def delete_orphans() -> int:
    """Delete the stack data of projects that no longer exist, which a deletion could not reach at the time."""
    targets = set(Stack.all_teams.using(WRITER_DB).values_list("target_team_id", flat=True).distinct())
    if not targets:
        return 0
    gone = targets - set(Team.objects.filter(id__in=targets).values_list("id", flat=True))
    if gone:
        delete_team_data(gone)
    return len(gone)


def sweep() -> dict[str, int]:
    """One pass of the cleanup schedule. Each unit runs on its own, so one that fails never starves the others;
    a failed unit reports -1."""
    units: dict[str, Callable[[], int]] = {
        "leases_recovered": lease.recover_expired_leases,
        "diffs_timed_out": close_timed_out_diffs,
        "saved_diffs_cleared": clear_expired_saved_diffs,
        "workdirs_removed": sweep_workdir,
        "managed_markers": managed.restore_markers,
        "orphans_deleted": delete_orphans,
    }
    results: dict[str, int] = {}
    for name, unit in units.items():
        try:
            results[name] = unit()
        except Exception:
            logger.exception("stacks_cleanup_unit_failed", unit=name)
            results[name] = -1
    return results


def delete_team_data(team_ids: Iterable[int]) -> None:
    """Delete every stack row of these projects. Safe to run again. Nothing in the main database refers to them."""
    team_ids = sorted(set(team_ids))
    if not team_ids or not database_ready():
        # Without the product's database no project has stack data.
        return
    try:
        with transaction.atomic(using=WRITER_DB):
            # A deleted environment's stacks go too: they carry its parent's `team_id` and its own target.
            StackDiff.all_teams.using(WRITER_DB).filter(target_team_id__in=team_ids).delete()
            stacks = Stack.all_teams.using(WRITER_DB).filter(Q(team_id__in=team_ids) | Q(target_team_id__in=team_ids))
            stack_ids = list(stacks.values_list("id", flat=True))
            for model in (StackSecret, StackNaturalClaim, StackBinding, StackRecordVersion, StackDiff):
                model.all_teams.using(WRITER_DB).filter(Q(team_id__in=team_ids) | Q(stack_id__in=stack_ids)).delete()
            stacks.delete()
    except DatabaseError:
        # Deleting the project goes ahead. The cleanup schedule deletes what is left once the database is back.
        logger.exception("stacks_team_data_deletion_deferred", team_ids=team_ids)
        return
    for team_id in team_ids:
        managed.forget_team(team_id)
