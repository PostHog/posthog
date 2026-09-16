from types import SimpleNamespace

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.temporal.activities.call_scanner_provider import _load_video_clock
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.video_clock import VideoClock, video_clock_from_export_context

# 0-58s kept, 58-62s cut, 62-80s kept: the second stretch starts 4s behind the session clock.
_PERIODS = [
    {"active": True, "ts_from_s": 0.0, "ts_to_s": 58.0, "recording_ts_from_s": 0.0, "recording_ts_to_s": 58.0},
    {"active": False, "ts_from_s": 58.0, "ts_to_s": 62.0, "recording_ts_from_s": 58.0, "recording_ts_to_s": 58.0},
    {"active": True, "ts_from_s": 62.0, "ts_to_s": 80.0, "recording_ts_from_s": 58.0, "recording_ts_to_s": 76.0},
]


class TestVideoClock:
    @parameterized.expand(
        [
            ("before any cut", 10.0, 10_000),
            ("the boundary instant belongs to the stretch before the cut", 58.0, 58_000),
            ("just past the boundary is the resumed moment", 58.5, 62_500),
            ("well past a cut", 70.0, 74_000),
            ("past the end clamps to the last kept moment", 999.0, 80_000),
        ]
    )
    def test_a_cited_video_second_becomes_the_session_moment_it_shows(
        self, _label: str, video_s: float, expected_ms: int
    ) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        assert clock.video_s_to_session_ms(video_s) == expected_ms

    @parameterized.expand(
        [
            ("before any cut", 10_000, 10.0),
            ("inside a cut collapses onto where the video resumes", 60_000, 58.0),
            ("after a cut", 74_000, 70.0),
        ]
    )
    def test_an_event_maps_onto_the_video_position_that_shows_it(
        self, _label: str, session_ms: int, expected_video_s: float
    ) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        assert clock.session_ms_to_video_s(session_ms) == expected_video_s

    def test_a_render_that_cut_nothing_leaves_both_clocks_the_same(self) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": []})
        assert clock is not None
        assert clock.is_identity
        assert clock.video_s_to_session_ms(42.0) == 42_000
        assert clock.session_ms_to_video_s(42_000) == 42.0

    def test_the_video_length_bounds_what_can_be_cited(self) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        assert clock.video_duration_s == 76.0
        assert VideoClock(spans=()).video_duration_s is None

    def test_an_asset_that_never_recorded_what_it_cut_has_no_clock(self) -> None:
        assert video_clock_from_export_context({"video_duration_s": 10.0}) is None
        assert video_clock_from_export_context(None) is None


class TestMissingCutMapIsRefusedUnlessProvablyUncut:
    """`_load_video_clock` falls back to identity only when the durations prove nothing was cut."""

    def _load(self, export_context: dict | None, session_duration_s: float | None) -> VideoClock:
        with patch.object(ExportedAsset, "objects") as objects:
            objects.filter.return_value.first.return_value = (
                SimpleNamespace(export_context=export_context) if export_context is not None else None
            )
            return _load_video_clock(1, 7, session_duration_s)

    def test_a_video_as_long_as_its_session_lost_nothing_so_identity_is_exact(self) -> None:
        assert self._load({"video_duration_s": 199.0}, 200.0).is_identity

    @parameterized.expand(
        [
            ("the video is materially shorter, so stretches were cut", {"video_duration_s": 120.0}, 200.0),
            ("no video duration to compare against", {"other": 1}, 200.0),
            ("no session duration to compare against", {"video_duration_s": 120.0}, None),
            ("no asset at all", None, 200.0),
        ]
    )
    def test_it_refuses_rather_than_place_citations_it_cannot_convert(
        self, _label: str, export_context: dict | None, session_duration_s: float | None
    ) -> None:
        with pytest.raises(ScannerFailureError):
            self._load(export_context, session_duration_s)
