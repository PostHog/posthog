"""Batched deletion of a team's stack frames and symbol sets before the Team cascade."""

import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db.models import QuerySet

from posthog.models.utils import transaction_with_timeouts

from products.error_tracking.backend.models import (
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
    delete_symbol_set_contents_many,
)

# A batch can wait on row locks that an earlier, timed-out deletion attempt still holds. These limits make the
# batch fail fast instead, and keep its own locks short. They match the limits on the Team cascade.
BATCH_LOCK_TIMEOUT_MS = 30_000
BATCH_STATEMENT_TIMEOUT_MS = 120_000


class StoredFileDeleteFailed(Exception):
    """Object storage did not delete every stored file of a symbol set batch, so the batch keeps its rows."""


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
        frames,
        lambda last_key: frames.filter(raw_id__gte=last_key).order_by("raw_id").values_list("id", "raw_id"),
        should_stop,
        batch_size,
    ):
        return False
    symbol_sets = ErrorTrackingSymbolSet.objects.filter(team_id=team_id)
    return _delete_in_batches(
        symbol_sets,
        lambda last_key: symbol_sets.filter(ref__gte=last_key).order_by("ref").values_list("id", "ref", "storage_ptr"),
        should_stop,
        batch_size,
        before_delete=_delete_stored_files,
    )


def _delete_stored_files(batch: list[tuple[Any, ...]]) -> None:
    # The files go before the rows. When a file delete fails, the rows keep their storage pointers, so a retry of
    # the purge finds the files again. Object storage treats the delete of a missing object as a success.
    storage_ptrs = [row[2] for row in batch if row[2]]
    if not storage_ptrs or not settings.OBJECT_STORAGE_ENABLED:
        return
    failed = delete_symbol_set_contents_many(storage_ptrs)
    if failed:
        raise StoredFileDeleteFailed(f"Object storage did not delete {len(failed)} stored symbol set files")


def _delete_in_batches(
    team_rows: QuerySet[Any],
    keys_from: Callable[[str], QuerySet[Any, tuple[Any, ...]]],
    should_stop: Callable[[], bool] | None,
    batch_size: int,
    before_delete: Callable[[list[tuple[Any, ...]]], None] | None = None,
) -> bool:
    # Each batch resumes the walk of the (team_id, key) unique index at the last key it deleted, so no batch reads
    # the index entries of rows that earlier batches deleted.
    last_key = ""
    while True:
        if should_stop is not None and should_stop():
            return False
        # Every statement runs under the limits, and the stored file deletes run between the two transactions.
        with transaction_with_timeouts(BATCH_LOCK_TIMEOUT_MS, BATCH_STATEMENT_TIMEOUT_MS):
            batch = list(keys_from(last_key)[:batch_size])
        if not batch:
            return True
        if before_delete is not None:
            before_delete(batch)
        with transaction_with_timeouts(BATCH_LOCK_TIMEOUT_MS, BATCH_STATEMENT_TIMEOUT_MS):
            team_rows.filter(id__in=[row[0] for row in batch]).delete()
        if len(batch) < batch_size:
            return True
        last_key = batch[-1][1]
        time.sleep(0.1)
