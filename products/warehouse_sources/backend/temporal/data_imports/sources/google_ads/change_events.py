import datetime as dt
from collections.abc import Callable, Iterator, Sequence
from typing import Generic, TypeVar

Row = TypeVar("Row")

CHANGE_EVENT_ROW_LIMIT = 10_000
CHANGE_EVENT_LOOKBACK_SECONDS = 24 * 60 * 60


class ChangeEventReader(Generic[Row]):
    def __init__(
        self,
        fields: Sequence[str],
        fetch: Callable[[str], list[Row]],
        safe_point: Callable[[], None],
    ) -> None:
        self.fields = fields
        self.fetch = fetch
        self.safe_point = safe_point

    @staticmethod
    def start_time(
        now: dt.datetime,
        watermark: dt.datetime | dt.date | str | None,
        requested_start: dt.date | None,
    ) -> dt.datetime:
        # Google rejects queries outside its retention window, including the normal two-year backfill.
        earliest = (now - dt.timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        if isinstance(watermark, str):
            watermark = dt.datetime.fromisoformat(watermark)
        if watermark is None:
            watermark = requested_start
        if isinstance(watermark, dt.date) and not isinstance(watermark, dt.datetime):
            watermark = dt.datetime.combine(watermark, dt.time())
        # The stored field is an account-local wall time; a cursor's UTC tag does not convert it.
        return max(earliest, watermark.replace(tzinfo=None) if watermark is not None else earliest)

    def read(self, start: dt.datetime, end: dt.datetime) -> Iterator[list[Row]]:
        if start >= end:
            return
        query = (
            f"SELECT {','.join(self.fields)} FROM change_event "
            f"WHERE change_event.change_date_time >= '{start:%Y-%m-%d %H:%M:%S}' "
            f"AND change_event.change_date_time < '{end:%Y-%m-%d %H:%M:%S}' "
            f"ORDER BY change_event.change_date_time ASC LIMIT {CHANGE_EVENT_ROW_LIMIT}"
        )
        rows = self.fetch(query)
        if len(rows) >= CHANGE_EVENT_ROW_LIMIT:
            # Pagination cannot recover rows beyond GAQL LIMIT; retry disjoint, smaller time windows.
            del rows
            self.safe_point()
            seconds = int((end - start).total_seconds())
            if seconds <= 1:
                raise ValueError("Google Ads change history reached 10,000 changes in one second. Contact support.")
            middle = start + dt.timedelta(seconds=seconds // 2)
            yield from self.read(start, middle)
            yield from self.read(middle, end)
            return
        for offset in range(0, len(rows), 5000):
            yield rows[offset : offset + 5000]
        self.safe_point()
