"""Batched deletion of a team's stack frames and symbol sets before the Team cascade."""

import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db.models import QuerySet

import structlog

from posthog.models.utils import transaction_with_timeouts

from products.error_tracking.backend.models import (
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
    delete_symbol_set_contents_many,
)

logger = structlog.get_logger(__name__)

# A batch can wait on row locks that an earlier, timed-out deletion attempt still holds. These limits make the
# batch fail fast instead, and keep its own locks short. They match the limits on the Team cascade.
BATCH_LOCK_TIMEOUT_MS = 30_000
BATCH_STATEMENT_TIMEOUT_MS = 120_000


def delete_stack_frames_and_symbol_sets_for_team(
    team_id: int, should_stop: Callable[[], bool] | None = None, batch_size: int = 10000
) -> bool:
    """Delete the team's stack frames, then its symbol sets and their stored files, in batches.

    Return False when ``should_stop`` ended the purge first.

    The Team cascade would clear ``symbol_set_id`` on the frames in one UPDATE that lists every symbol set of the
    team, and hold its locks until the whole cascade commits. The frames go first, so no symbol set batch finds a
    frame to update. ``should_stop`` is checked before each batch.
    """
    frames = ErrorTrackingStackFrame.objects.filter(team_id=team_id)
    if not _delete_in_batches(
        lambda last_key: frames.filter(raw_id__gte=last_key).order_by("raw_id").values_list("id", "raw_id"),
        lambda ids: _delete_rows(frames, ids),
        should_stop,
        batch_size,
    ):
        return False
    symbol_sets = ErrorTrackingSymbolSet.objects.filter(team_id=team_id)
    return _delete_in_batches(
        lambda last_key: symbol_sets.filter(ref__gte=last_key).order_by("ref").values_list("id", "ref"),
        lambda ids: _delete_symbol_set_rows(symbol_sets, ids),
        should_stop,
        batch_size,
    )


def _delete_rows(team_rows: QuerySet[Any], ids: list[Any]) -> list[str]:
    team_rows.filter(id__in=ids).delete()
    return []


def _delete_symbol_set_rows(symbol_sets: QuerySet[ErrorTrackingSymbolSet], ids: list[Any]) -> list[str]:
    storage_ptrs = [ptr for ptr in symbol_sets.filter(id__in=ids).values_list("storage_ptr", flat=True) if ptr]
    symbol_sets.filter(id__in=ids).delete()
    return storage_ptrs


def _delete_stored_files(storage_ptrs: list[str]) -> None:
    # The rows are already gone, so a failed delete leaves an orphan object rather than a row that points nowhere.
    if not storage_ptrs or not settings.OBJECT_STORAGE_ENABLED:
        return
    try:
        failed = delete_symbol_set_contents_many(storage_ptrs)
    except Exception:
        logger.exception("error_tracking.team_purge.storage_delete_failed", storage_objects=len(storage_ptrs))
        return
    if failed:
        logger.warning("error_tracking.team_purge.storage_delete_failed", storage_objects_failed=len(failed))


def _delete_in_batches(
    keys_from: Callable[[str], QuerySet[Any, tuple[Any, str]]],
    delete_rows: Callable[[list[Any]], list[str]],
    should_stop: Callable[[], bool] | None,
    batch_size: int,
) -> bool:
    # Each batch resumes the walk of the (team_id, key) unique index at the last key it deleted, so no batch reads
    # the index entries of rows that earlier batches deleted.
    last_key = ""
    while True:
        if should_stop is not None and should_stop():
            return False
        with transaction_with_timeouts(BATCH_LOCK_TIMEOUT_MS, BATCH_STATEMENT_TIMEOUT_MS):
            batch = list(keys_from(last_key)[:batch_size])
            storage_ptrs = delete_rows([row[0] for row in batch]) if batch else []
        # The stored files go after the commit, so a slow object store never holds the batch's row locks.
        _delete_stored_files(storage_ptrs)
        if len(batch) < batch_size:
            return True
        last_key = batch[-1][1]
        time.sleep(0.1)
