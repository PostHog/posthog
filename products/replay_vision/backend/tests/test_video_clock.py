from dataclasses import replace
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.temporal.activities.call_scanner_provider import (
    _extract_segments,
    _load_video_clock,
)
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.scanners.base import ChipSegment
from products.replay_vision.backend.temporal.scanners.summarizer import (
    IdleBreak,
    SummaryChapterResponse,
    long_idle_breaks,
    resolve_chapters,
)
from products.replay_vision.backend.temporal.video_clock import (
    ActiveSpan,
    IdleStretch,
    VideoClock,
    video_clock_from_export_context,
)

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
            ("a second shared across a cut is the resumed moment, not the one before it", 58.0, 62_000),
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
            ("the video is longer than its session, so it is not this recording", {"video_duration_s": 500.0}, 200.0),
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


def test_the_first_chapter_starts_with_the_session_when_the_render_starts_later() -> None:
    clock = VideoClock(
        spans=(ActiveSpan(session_from_s=0.333, session_to_s=60.0, video_from_s=0.0, video_to_s=59.667),)
    )
    resolved = resolve_chapters([_chapter(0, "Browses")], 60_000, clock)
    assert (resolved[0].start_ms, resolved[0].end_ms) == (0, 60_000)


def test_only_long_idle_between_activity_is_named_to_the_model() -> None:
    clock = VideoClock(spans=(), inactive=((0, 90), (100, 130), (200, 300), (320, 400)))
    assert long_idle_breaks(clock, 400_000) == (IdleBreak(video_s=300, idle_s=100),)
    # Only the longest stretches count, so a session of many long idles keeps a bounded timeline.
    many = VideoClock(spans=(), inactive=tuple((i * 200 + 10, i * 200 + 70 + i) for i in range(15)))
    assert [b.video_s for b in long_idle_breaks(many, 3_100_000)] == [i * 200 + 70 + i for i in range(5, 15)]


def test_the_players_inactive_periods_are_the_idle_stretches() -> None:
    clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
    assert clock is not None
    assert clock.inactive_session_ms(80_000) == [IdleStretch(start_ms=58_000, end_ms=62_000)]


class TestCitationsPastTheVideoEnd:
    def test_an_invented_time_is_dropped_rather_than_clamped_to_the_end(self) -> None:
        # The clock clamps past its last span, so without an explicit bound this lands on the recording end.
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        _, segments = _extract_segments("stuck here (t 9999)", 80_000, clock)
        assert [s for s in segments if isinstance(s, ChipSegment)] == []

    def test_one_second_past_the_end_is_still_invented(self) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        _, segments = _extract_segments("just past it (t 77)", 80_000, clock)
        assert [s for s in segments if isinstance(s, ChipSegment)] == []

    def test_a_genuine_final_moment_still_becomes_a_chip(self) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        _, segments = _extract_segments("ends here (t 76)", 80_000, clock)
        assert [s.timestamp_ms for s in segments if isinstance(s, ChipSegment)] == [80_000]


def _chapter(start_t: int, title: str = "Part", thumbnail_t: int | None = None) -> SummaryChapterResponse:
    return SummaryChapterResponse(start_t=start_t, title=title, thumbnail_t=thumbnail_t)


class TestResolveChapters:
    @parameterized.expand(
        [
            (
                "chapters tile the session, and a start after the cut moves onto the session clock",
                [_chapter(0, "Opens the app", 10), _chapter(30, "Edits a form", 40), _chapter(60, "Saves", 70)],
                [
                    (0, 30_000, "Opens the app", 10_000),
                    (30_000, 64_000, "Edits a form", 40_000),
                    (64_000, 80_000, "Saves", 74_000),
                ],
            ),
            (
                "out of order input is sorted and a repeated start keeps the first chapter",
                [_chapter(30, "Second"), _chapter(0, "First"), _chapter(30, "Duplicate")],
                [(0, 30_000, "First", 15_000), (30_000, 80_000, "Second", 55_000)],
            ),
            (
                "the first chapter starts at 0 even when the model skipped the page load",
                [_chapter(5, "Only part", 20)],
                [(0, 80_000, "Only part", 20_000)],
            ),
            (
                "a start at or past the video's end is invented and dropped",
                [_chapter(0, "Real"), _chapter(76, "Invented"), _chapter(900, "Invented")],
                [(0, 80_000, "Real", 40_000)],
            ),
            (
                "a thumbnail outside its chapter falls back to the midpoint",
                [_chapter(0, "Browses", 50), _chapter(30, "Buys")],
                [(0, 30_000, "Browses", 15_000), (30_000, 80_000, "Buys", 55_000)],
            ),
            (
                "a title that was only a leaked citation marker is dropped",
                [_chapter(0, "Browses"), _chapter(30, "(t 30)")],
                [(0, 80_000, "Browses", 40_000)],
            ),
            (
                "a chapter with no start is dropped and negative starts clamp to 0",
                [
                    SummaryChapterResponse(title="No start"),
                    _chapter(-9, "Opens"),
                    _chapter(-2, "Also opens"),
                    _chapter(30, "Buys"),
                ],
                [(0, 30_000, "Opens", 15_000), (30_000, 80_000, "Buys", 55_000)],
            ),
            ("no chapters stay no chapters", [], []),
        ]
    )
    def test_the_models_chapters_are_repaired_onto_the_session_clock(
        self,
        _label: str,
        chapters: list[SummaryChapterResponse],
        expected: list[tuple[int, int, str, int]],
    ) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        # Only the cut map, so these cases cover the repair on its own; idle stretches have their own test.
        resolved = resolve_chapters(chapters, 80_000, replace(clock, inactive=()))
        assert [(c.start_ms, c.end_ms, c.title, c.thumbnail_ms) for c in resolved] == expected

    @parameterized.expand(
        [
            (
                "a short pause stays inside its chapter",
                [(40, 70)],
                [_chapter(0, "Reads docs", 50), _chapter(200, "Signs up")],
                [
                    ("activity", 0, 200_000, "Reads docs", 50_000),
                    ("activity", 200_000, 400_000, "Signs up", 300_000),
                ],
            ),
            (
                "a boundary a second past a long idle snaps to its end",
                [(100, 200)],
                [_chapter(0, "Browses"), _chapter(201, "Buys")],
                [
                    ("activity", 0, 100_000, "Browses", 50_000),
                    ("idle", 100_000, 200_000, "Idle", None),
                    ("activity", 200_000, 400_000, "Buys", 300_000),
                ],
            ),
            (
                "a long idle inside a chapter splits it and both sides keep the title",
                [(100, 200)],
                [_chapter(0, "Reads docs", 150)],
                [
                    ("activity", 0, 100_000, "Reads docs", 50_000),
                    ("idle", 100_000, 200_000, "Idle", None),
                    ("activity", 200_000, 400_000, "Reads docs", 300_000),
                ],
            ),
            (
                "long idle at the start and the end of the session",
                [(0, 70), (320, 400)],
                [_chapter(0, "Browses", 100)],
                [
                    ("idle", 0, 70_000, "Idle", None),
                    ("activity", 70_000, 320_000, "Browses", 100_000),
                    ("idle", 320_000, 400_000, "Idle", None),
                ],
            ),
            (
                "a short chapter the model gave its own entry is kept, however short",
                [],
                [_chapter(0, "Browses"), _chapter(100, "Rage clicks buy button"), _chapter(102, "Buys")],
                [
                    ("activity", 0, 100_000, "Browses", 50_000),
                    ("activity", 100_000, 102_000, "Rage clicks buy button", 101_000),
                    ("activity", 102_000, 400_000, "Buys", 251_000),
                ],
            ),
            (
                "a sliver of activity between two long idles folds into them",
                [(0, 100), (101, 400)],
                [_chapter(0, "Browses")],
                [("idle", 0, 400_000, "Idle", None)],
            ),
        ]
    )
    def test_long_inactive_stretches_become_idle_chapters(
        self,
        _label: str,
        inactive: list[tuple[float, float]],
        chapters: list[SummaryChapterResponse],
        expected: list[tuple[str, int, int, str, int | None]],
    ) -> None:
        clock = VideoClock(spans=(), inactive=tuple(inactive))
        resolved = resolve_chapters(chapters, 400_000, clock)
        assert [(c.kind, c.start_ms, c.end_ms, c.title, c.thumbnail_ms) for c in resolved] == expected
