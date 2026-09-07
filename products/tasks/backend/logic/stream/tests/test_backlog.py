from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.stream.backlog import TaskRunStreamBacklogIndex, format_log_cursor, parse_log_cursor


class TestLogCursor(SimpleTestCase):
    @parameterized.expand(
        [
            ("log_cursor", "log-0", 0),
            ("log_cursor_large", "log-1234", 1234),
            ("redis_id", "1725370000000-0", None),
            ("malformed_index", "log-abc", None),
            ("empty", "", None),
            ("negative", "log--100", None),
            ("signed", "log-+7", None),
            ("underscored", "log-1_0", None),
            ("whitespace", "log- 1", None),
            ("non_ascii_digit", "log-١", None),
        ]
    )
    def test_parse_log_cursor(self, _name: str, cursor: str, expected: int | None) -> None:
        assert parse_log_cursor(cursor) == expected

    def test_format_round_trips(self) -> None:
        assert parse_log_cursor(format_log_cursor(42)) == 42


class TestTaskRunStreamBacklogIndex(SimpleTestCase):
    def test_covers_exact_ids_and_coalesced_ranges(self) -> None:
        index = TaskRunStreamBacklogIndex(
            [
                {"type": "notification", "event_id": "boot1-10"},
                {"type": "notification", "event_id": "boot1-20", "first_event_id": "boot1-14"},
                {"type": "notification"},
            ]
        )

        assert index.covers({"event_id": "boot1-10"})
        assert index.covers({"event_id": "boot1-14"})
        assert index.covers({"event_id": "boot1-17"})
        assert index.covers({"event_id": "boot1-20"})
        assert not index.covers({"event_id": "boot1-13"})
        assert not index.covers({"event_id": "boot1-21"})
        assert not index.covers({"event_id": "boot2-17"})
        assert not index.covers({"type": "notification"})
        assert not index.covers({"event_id": ""})

    def test_range_across_boot_prefixes_falls_back_to_exact_ids(self) -> None:
        index = TaskRunStreamBacklogIndex(
            [{"type": "notification", "event_id": "boot2-3", "first_event_id": "boot1-90"}]
        )

        assert index.covers({"event_id": "boot1-90"})
        assert index.covers({"event_id": "boot2-3"})
        assert not index.covers({"event_id": "boot1-91"})
        assert not index.covers({"event_id": "boot2-1"})

    def test_has_gap_before(self) -> None:
        index = TaskRunStreamBacklogIndex(
            [
                {"type": "notification", "event_id": "boot1-10"},
                {"type": "notification", "event_id": "boot1-20", "first_event_id": "boot1-14"},
            ]
        )

        assert not index.has_gap_before({"event_id": "boot1-11"})  # predecessor is an exact id
        assert not index.has_gap_before({"event_id": "boot1-21"})  # predecessor closes a range
        assert index.has_gap_before({"event_id": "boot1-13"})  # boot1-12 is in neither store
        assert index.has_gap_before({"event_id": "boot2-5"})  # unknown boot, mid-sequence
        assert not index.has_gap_before({"event_id": "boot2-1"})  # a boot's first event has no predecessor
        assert not index.has_gap_before({"type": "notification"})  # unstamped entries carry no signal
