"""Batched deletion of a team's stack frames and symbol sets before the Team cascade."""

import time
from collections.abc import Callable
from typing import Any

from django.db.models import QuerySet

from products.error_tracking.backend.models import ErrorTrackingStackFrame, ErrorTrackingSymbolSet


def delete_stack_frames_and_symbol_sets_for_team(
    team_id: int, should_stop: Callable[[], bool] | None = None, batch_size: int = 10000
) -> bool:
    """Delete the team's stack frames, then its symbol sets, in batches. Return False when ``should_stop`` ended the purge first.

    The Team cascade would clear ``symbol_set_id`` on the frames in one UPDATE that lists every symbol set of the
    team, and hold its locks until the whole cascade commits. The frames go first, so no symbol set batch finds a
    frame to update. ``should_stop`` is checked before each batch.
    """
    if not _delete_in_batches(
        ErrorTrackingStackFrame.objects.filter(team_id=team_id), "raw_id", should_stop, batch_size
    ):
        return False
    return _delete_in_batches(ErrorTrackingSymbolSet.objects.filter(team_id=team_id), "ref", should_stop, batch_size)


def _delete_in_batches(
    team_rows: QuerySet[Any], key: str, should_stop: Callable[[], bool] | None, batch_size: int
) -> bool:
    # Each batch resumes the walk of the (team_id, key) unique index at the last key it deleted, so no batch reads
    # the index entries of rows that earlier batches deleted.
    last_key = ""
    while True:
        if should_stop is not None and should_stop():
            return False
        batch = list(team_rows.filter(**{f"{key}__gte": last_key}).order_by(key).values_list("id", key)[:batch_size])
        if not batch:
            return True
        team_rows.filter(id__in=[row[0] for row in batch]).delete()
        if len(batch) < batch_size:
            return True
        last_key = batch[-1][1]
        time.sleep(0.1)
