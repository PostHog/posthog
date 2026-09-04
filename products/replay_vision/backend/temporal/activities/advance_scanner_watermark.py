from django.db import OperationalError, connection, transaction
from django.db.models import Q

import psycopg.errors
from temporalio import activity
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import SCANNER_WATERMARK_BUSY_ERROR_TYPE
from products.replay_vision.backend.temporal.metrics import record_watermark_advance
from products.replay_vision.backend.temporal.sweep_types import AdvanceScannerWatermarkInputs


@activity.defn
@track_activity()
def advance_scanner_watermark_activity(inputs: AdvanceScannerWatermarkInputs) -> None:
    """Advance the sweep keyset; never regress it.

    Concurrent ticks and delayed Temporal retries race on this row, and an unconditional write lets a
    stale attempt drag the keyset backwards — the next sweep then re-fetches ground a newer tick
    already covered, and every re-dispatched session burns an insert on UNIQUE(scanner_id, session_id).
    The WHERE admits only a strictly newer (last_swept_at, last_seen_session_id) keyset, so of N racing
    writers the newest lands and the rest no-op. Deep-sweep progress rides along only with an admitted
    fast keyset: a rejected write's deep cursor is as stale as its fast one, and dropping it only makes
    the deep pass re-walk a window it tolerates re-walking.
    """
    updates: dict[str, object] = {
        "last_swept_at": inputs.new_last_swept_at,
        "last_seen_session_id": inputs.new_last_seen_session_id,
    }
    if inputs.new_last_deep_swept_at is not None:
        updates["deep_swept_through"] = inputs.new_last_deep_swept_at
        updates["deep_seen_session_id"] = inputs.new_last_deep_seen_session_id
    try:
        with transaction.atomic():
            # Bounded like the admission lock: a writer queued behind an open transaction on this row
            # gives up after 2s and defers to the activity retry instead of camping in Postgres's lock
            # queue with a connection held. 2s absorbs the row's brief holders (scanner save(),
            # admission-budget updates), which NOWAIT would turn into a failure on every brush.
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '2s'")
            updated = ReplayScanner.objects.filter(
                Q(last_swept_at__lt=inputs.new_last_swept_at)
                | Q(
                    last_swept_at=inputs.new_last_swept_at,
                    last_seen_session_id__lt=inputs.new_last_seen_session_id,
                ),
                pk=inputs.scanner_id,
            ).update(**updates)
    except OperationalError as e:
        if not isinstance(e.__cause__, psycopg.errors.LockNotAvailable):
            raise
        record_watermark_advance("busy")
        activity.logger.info(
            "advance_scanner_watermark: row busy; deferring to activity retry",
            extra={"scanner_id": str(inputs.scanner_id)},
        )
        raise ApplicationError(
            "Scanner watermark row busy; retried with backoff",
            type=SCANNER_WATERMARK_BUSY_ERROR_TYPE,
        ) from e
    if updated:
        record_watermark_advance("advanced")
        return
    if ReplayScanner.objects.filter(pk=inputs.scanner_id).exists():
        # A newer tick already carried the keyset past this attempt's; dropping the write is the point.
        record_watermark_advance("superseded")
        activity.logger.info(
            "advance_scanner_watermark: superseded by a newer keyset",
            extra={"scanner_id": str(inputs.scanner_id)},
        )
    else:
        record_watermark_advance("scanner_missing")
        activity.logger.info(
            "advance_scanner_watermark: scanner no longer exists",
            extra={"scanner_id": str(inputs.scanner_id)},
        )
