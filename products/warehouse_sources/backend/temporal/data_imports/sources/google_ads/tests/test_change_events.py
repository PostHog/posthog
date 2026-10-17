import re
import datetime as dt

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.change_events import ChangeEventReader


class TestChangeEventReader:
    @pytest.mark.parametrize(
        "watermark, requested, expected",
        [
            (None, None, dt.datetime(2026, 3, 3)),
            (None, dt.date(2020, 1, 1), dt.datetime(2026, 3, 3)),
            (None, dt.date(2026, 3, 20), dt.datetime(2026, 3, 20)),
            ("2020-01-01 00:00:00", None, dt.datetime(2026, 3, 3)),
            ("2026-03-25 12:00:00", dt.date(2026, 3, 28), dt.datetime(2026, 3, 25, 12)),
            (dt.datetime(2026, 3, 25, 12, tzinfo=dt.UTC), None, dt.datetime(2026, 3, 25, 12)),
        ],
    )
    def test_bounds_backfill_and_preserves_account_local_cursor(self, watermark, requested, expected):
        assert ChangeEventReader.start_time(dt.datetime(2026, 4, 1, 12), watermark, requested) == expected

    def test_splits_saturated_queries_without_losing_boundary_events(self):
        start = dt.datetime(2026, 4, 1, 12)
        events = [(start + dt.timedelta(seconds=i // 5001), i) for i in range(20_004)]
        queries: list[str] = []

        def fetch(query: str) -> list[tuple[dt.datetime, int]]:
            queries.append(query)
            lower, upper = [dt.datetime.fromisoformat(value) for value in re.findall(r"'([^']+)'", query)]
            return [event for event in events if lower <= event[0] < upper][:10_000]

        reader = ChangeEventReader(["change_event.resource_name"], fetch, lambda: None)
        batches = list(reader.read(start, start + dt.timedelta(seconds=4)))
        assert [event for batch in batches for event in batch] == events
        assert max(map(len, batches)) <= 5000
        assert len(queries) == 7
        assert "change_event.change_date_time >= '2026-04-01 12:00:00'" in queries[0]
        assert "change_event.change_date_time < '2026-04-01 12:00:04'" in queries[0]
        assert "ORDER BY change_event.change_date_time ASC LIMIT 10000" in queries[0]
        assert all("segments.date" not in query for query in queries)

    def test_fails_instead_of_returning_partial_history_at_one_second_limit(self):
        reader = ChangeEventReader(["change_event.resource_name"], lambda query: list(range(10_000)), lambda: None)
        with pytest.raises(ValueError, match="10,000 changes in one second"):
            list(reader.read(dt.datetime(2026, 4, 1, 12), dt.datetime(2026, 4, 1, 12, 0, 1)))

    def test_reaches_a_safe_point_after_an_empty_result(self):
        safe_points: list[bool] = []
        reader: ChangeEventReader[int] = ChangeEventReader(
            ["change_event.resource_name"], lambda query: [], lambda: safe_points.append(True)
        )
        assert list(reader.read(dt.datetime(2026, 4, 1), dt.datetime(2026, 4, 2))) == []
        assert safe_points == [True]
