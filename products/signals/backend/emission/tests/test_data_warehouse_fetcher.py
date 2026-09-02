from types import SimpleNamespace

from unittest import TestCase
from unittest.mock import MagicMock, patch

from products.signals.backend.emission.fetchers.data_warehouse import _CURSOR_ALIAS, data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

_FETCHER_MODULE = "products.signals.backend.emission.fetchers.data_warehouse"

_CONFIG = SignalSourceTableConfig(
    source_product="linear",
    source_type="issue",
    emitter=lambda team_id, record: None,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    fields=("id", "created_at"),
    max_records=3,  # small page size so a handful of rows spans several pages
)


def _page(rows: list[tuple[str, str]]) -> SimpleNamespace:
    """A fake HogQL result: each row is (id, created_at); the fetcher's cursor alias echoes created_at."""
    columns = ["id", "created_at", _CURSOR_ALIAS]
    return SimpleNamespace(columns=columns, results=[[rid, created_at, created_at] for rid, created_at in rows])


class TestDataWarehouseFetcher(TestCase):
    context = {"table_name": "linear.issues", "last_synced_at": "2026-08-24T00:00:00"}

    def _run(self, pages: list[SimpleNamespace]) -> tuple[list[dict], int]:
        with patch(f"{_FETCHER_MODULE}.execute_hogql_query", side_effect=pages) as mock_exec:
            records = data_warehouse_record_fetcher(MagicMock(), _CONFIG, self.context)
        return records, mock_exec.call_count

    def test_single_short_page_stops_after_one_query(self):
        records, calls = self._run([_page([("A", "t1"), ("B", "t2")])])

        assert [r["id"] for r in records] == ["A", "B"]
        assert calls == 1
        # The keyset cursor column must never reach the emitter.
        assert all(_CURSOR_ALIAS not in r for r in records)

    def test_overflow_beyond_one_page_is_fetched_not_dropped(self):
        # A full page keeps paging; the bug this guards dropped everything past the first page.
        # Each full page trims its last partition group and refetches it, so a keyset DB re-returns
        # that row on the next page (t3 and t5 below), and the fetcher stitches each row in once.
        records, calls = self._run(
            [
                _page([("A", "t1"), ("B", "t2"), ("C", "t3")]),
                _page([("C", "t3"), ("D", "t4"), ("E", "t5")]),
                _page([("E", "t5")]),
            ]
        )

        assert [r["id"] for r in records] == ["A", "B", "C", "D", "E"]
        assert calls == 3

    def test_full_page_ending_a_partition_group_defers_the_group(self):
        # C and D share t3 at the page boundary: the group is trimmed and refetched whole next page,
        # so no row is split across pages and none is duplicated.
        records, calls = self._run(
            [
                _page([("A", "t1"), ("B", "t2"), ("C", "t3")]),
                _page([("C", "t3"), ("D", "t3"), ("E", "t4")]),
                _page([("E", "t4")]),
            ]
        )

        assert [r["id"] for r in records] == ["A", "B", "C", "D", "E"]
        assert calls == 3

    def test_full_page_of_one_partition_value_advances_to_avoid_a_stall(self):
        # A whole page sharing one partition value cannot be split; the fetcher advances past it
        # rather than looping forever, and warns that the overflow is deferred.
        with patch(f"{_FETCHER_MODULE}.logger") as mock_logger:
            records, calls = self._run(
                [
                    _page([("A", "t1"), ("B", "t1"), ("C", "t1")]),
                    _page([("D", "t2")]),
                ]
            )

        assert [r["id"] for r in records] == ["A", "B", "C", "D"]
        assert calls == 2
        assert mock_logger.warning.called
