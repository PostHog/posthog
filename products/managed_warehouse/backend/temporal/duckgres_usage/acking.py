"""The day-boundary ack rule — the single invariant the replace design hangs on.

We only ever ack at UTC day boundaries, never mid-day. Duckgres watermarks are
bucket-START labels and ack deletes `bucket_start <= watermark`, so:

- acking exact midnight would delete the new day's first bucket;
- acking mid-day would make the next pull serve a partial-day remainder, which
  the replace-upsert would then use to overwrite the full day.

The safe "everything through day D is ours" ack is `midnight(D+1) - 1s`: it
covers every bucket label of day D (the last is `midnight(D+1) - width` for
any width >= 1s) and no label of day D+1. We always ack through the end of the
day BEFORE watermark_high's date — conservative (watermark_high's own day gets
acked on the first pull after the next midnight), never wrong, and independent
of duckgres's bucket width.
"""

import datetime as dt


def day_boundary_ack(*, watermark_low: dt.datetime, watermark_high: dt.datetime) -> dt.datetime | None:
    """The watermark to ack after committing a pull, or None if no new day closed.

    Call only after the pull's rows are committed — acking hands custody to us.
    """
    if watermark_high <= watermark_low:
        return None

    open_day = watermark_high.astimezone(dt.UTC).date()
    boundary = dt.datetime.combine(open_day, dt.time.min, tzinfo=dt.UTC) - dt.timedelta(seconds=1)
    if boundary <= watermark_low.astimezone(dt.UTC):
        return None
    return boundary
