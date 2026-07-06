import datetime as dt
from typing import Any

from parameterized import parameterized

from products.replay_vision.backend.temporal.events_tool import (
    EventsIndex,
    build_events_index,
    dispatch_events_tool,
    get_events_around,
)
from products.replay_vision.backend.temporal.types import EventTable, ScannerLlmInputs, SessionMetadata

_COLUMNS = ["event_uuid", "event", "timestamp", "$current_url", "$window_id", "$event_type", "elements_chain_texts"]


def _index(
    rows: list[list[Any]],
    event_timestamps: dict[str, int],
    *,
    url_mapping: dict[str, str] | None = None,
    window_mapping: dict[str, str] | None = None,
) -> EventsIndex:
    return build_events_index(
        ScannerLlmInputs(
            session_id="s",
            team_id=1,
            events=EventTable(columns=_COLUMNS, rows=rows),
            url_mapping=url_mapping or {},
            window_mapping=window_mapping or {},
            event_timestamps=event_timestamps,
            metadata=SessionMetadata(
                start_time=dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC),
                end_time=dt.datetime(2026, 5, 1, 12, 5, 0, tzinfo=dt.UTC),
                duration_seconds=300.0,
            ),
        )
    )


def _row(uuid: str, event: str, ts: Any, url: Any, window: Any, etype: Any, texts: Any) -> list[Any]:
    return [uuid, event, ts, url, window, etype, texts]


class TestGetEventsAround:
    def test_returns_only_events_within_the_window(self) -> None:
        rows = [
            _row("u1", "$pageview", None, "url_1", None, None, []),
            _row("u2", "$rageclick", None, "url_1", "window_1", "click", ["Buy now"]),
            _row("u3", "$autocapture", None, "url_2", None, "click", []),
            _row("u4", "$exception", None, "url_2", None, None, []),
        ]
        offsets = {"u1": 5_000, "u2": 30_000, "u3": 35_000, "u4": 90_000}
        out = get_events_around(_index(rows, offsets), rec_t=30, window_s=10)
        # 30 and 35 are within ±10 of 30; 5 and 90 are not.
        assert [e["rec_t"] for e in out] == [30, 35]
        assert [e["event"] for e in out] == ["$rageclick", "$autocapture"]

    def test_resolves_url_and_window_tokens_and_drops_internal_and_empty(self) -> None:
        rows = [_row("u2", "$rageclick", "2026-05-01T12:00:30Z", "url_1", "window_1", "click", ["Buy now"])]
        out = get_events_around(
            _index(
                rows,
                {"u2": 30_000},
                url_mapping={"url_1": "https://app.x/cart"},
                window_mapping={"window_1": "win-abc"},
            ),
            rec_t=30,
        )
        (event,) = out
        assert event["$current_url"] == "https://app.x/cart"
        assert event["$window_id"] == "win-abc"
        assert event["elements_chain_texts"] == ["Buy now"]
        # uuid + absolute timestamp are internal; not surfaced to the model.
        assert "event_uuid" not in event
        assert "timestamp" not in event

    def test_window_membership_keys_off_recording_relative_offset_not_absolute_timestamp(self) -> None:
        # The absolute `timestamp` column is deliberately inconsistent with the recording-relative offset.
        # Membership must follow `event_timestamps` (ms since recording start) — the footer/REC_T anchor —
        # never the absolute timestamp or any session-derived time.
        rows = [_row("u1", "$pageview", "1999-01-01T00:00:00Z", "url_1", None, None, [])]
        out = get_events_around(_index(rows, {"u1": 42_000}), rec_t=42, window_s=2)
        assert [e["rec_t"] for e in out] == [42]
        assert get_events_around(_index(rows, {"u1": 42_000}), rec_t=10, window_s=2) == []

    def test_caps_to_the_nearest_events(self) -> None:
        rows = [_row(f"u{i}", "$autocapture", None, "url_1", None, "click", []) for i in range(60)]
        # All within the window, but at increasing distance from rec_t=0.
        offsets = {f"u{i}": i * 1_000 for i in range(60)}
        out = get_events_around(_index(rows, offsets), rec_t=0, window_s=60)
        assert len(out) == 50  # capped
        assert out == sorted(out, key=lambda e: e["rec_t"])  # chronological
        assert max(e["rec_t"] for e in out) == 49  # the 10 farthest were dropped

    def test_clamps_window_and_rec_t(self) -> None:
        rows = [_row("u1", "$pageview", None, "url_1", None, None, [])]
        offsets = {"u1": 55_000}
        # window clamps to _MAX_WINDOW_S (60), so an event 55s away from rec_t=0 still matches.
        assert len(get_events_around(_index(rows, offsets), rec_t=0, window_s=9999)) == 1
        # negative rec_t clamps to 0.
        assert get_events_around(_index(rows, offsets), rec_t=-100, window_s=1) == []

    def test_empty_when_nothing_near(self) -> None:
        rows = [_row("u1", "$pageview", None, "url_1", None, None, [])]
        assert get_events_around(_index(rows, {"u1": 5_000}), rec_t=500, window_s=10) == []

    def test_skips_events_with_no_resolvable_offset(self) -> None:
        # u2 is absent from event_timestamps, so it must be dropped — not pinned to second 0. A genuine offset-0
        # event (u1) still shows there.
        rows = [
            _row("u1", "$pageview", None, "url_1", None, None, []),
            _row("u2", "$rageclick", None, "url_1", None, "click", []),
        ]
        out = get_events_around(_index(rows, {"u1": 0}), rec_t=0, window_s=5)
        assert [e["event"] for e in out] == ["$pageview"]


class _Call:
    def __init__(self, name: str, args: dict[str, Any]) -> None:
        self.name = name
        self.args = args


class TestDispatchEventsTool:
    def test_dispatches_to_get_events_around(self) -> None:
        rows = [_row("u1", "$rageclick", None, "url_1", None, "click", [])]
        index = _index(rows, {"u1": 30_000})
        result = dispatch_events_tool(_Call("get_events_around", {"rec_t": 30, "window_s": 5}), index)
        assert [e["rec_t"] for e in result["events"]] == [30]

    def test_defaults_window_when_omitted(self) -> None:
        rows = [_row("u1", "$rageclick", None, "url_1", None, "click", [])]
        result = dispatch_events_tool(_Call("get_events_around", {"rec_t": 30}), _index(rows, {"u1": 30_000}))
        assert len(result["events"]) == 1

    def test_rejects_unknown_tool(self) -> None:
        result = dispatch_events_tool(_Call("something_else", {}), _index([], {}))
        assert "error" in result

    @parameterized.expand(
        [
            ("float_string", "30.7"),
            ("float", 30.0),
            ("int_string", "30"),
        ]
    )
    def test_coerces_numeric_rec_t_variants(self, _label: str, rec_t: Any) -> None:
        rows = [_row("u1", "$rageclick", None, "url_1", None, "click", [])]
        result = dispatch_events_tool(_Call("get_events_around", {"rec_t": rec_t}), _index(rows, {"u1": 30_000}))
        assert [e["rec_t"] for e in result["events"]] == [30]

    @parameterized.expand(
        [
            ("null", None),
            ("prose", "about 30"),
            ("boolean", True),
            ("nan", "nan"),
        ]
    )
    def test_malformed_rec_t_returns_error_to_model_instead_of_raising(self, _label: str, rec_t: Any) -> None:
        result = dispatch_events_tool(_Call("get_events_around", {"rec_t": rec_t}), _index([], {}))
        assert "rec_t" in result["error"]

    def test_malformed_window_falls_back_to_default(self) -> None:
        rows = [_row("u1", "$rageclick", None, "url_1", None, "click", [])]
        index = _index(rows, {"u1": 30_000})
        result = dispatch_events_tool(_Call("get_events_around", {"rec_t": 30, "window_s": "wide"}), index)
        assert len(result["events"]) == 1
