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
    InactivePeriod,
    SummarizerOutput,
    SummarizerScanner,
    SummarizerSummaryResponse,
    SummaryChapterResponse,
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


def _chapter(start_t: int, title: str = "Part", thumbnail_t: int | None = None) -> SummaryChapterResponse:
    return SummaryChapterResponse(start_t=start_t, title=title, thumbnail_t=thumbnail_t)


def test_inactive_time_at_the_ends_is_left_out_of_the_chapters_and_listed_as_inactive() -> None:
    clock = VideoClock(
        spans=(ActiveSpan(session_from_s=10.0, session_to_s=60.0, video_from_s=0.0, video_to_s=50.0),),
        inactive=((0.0, 10.0), (60.0, 70.0)),
    )
    core = SummarizerSummaryResponse(title="t", summary="s", confidence=0.9, chapters=[_chapter(0, "Browses")])
    output = SummarizerScanner(prompt="p").resolve_session_clock(
        SummarizerOutput(title="t", summary="s", confidence=0.9), core, clock, 70_000
    )
    assert isinstance(output, SummarizerOutput)
    assert [(c.start_ms, c.end_ms) for c in output.chapters] == [(10_000, 60_000)]
    assert output.inactive_periods == [
        InactivePeriod(start_ms=0, end_ms=10_000),
        InactivePeriod(start_ms=60_000, end_ms=70_000),
    ]


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


class TestResolveChapters:
    def test_a_start_at_0_never_snaps_so_it_cannot_swallow_a_chapter_that_snaps_onto_an_early_cut(self) -> None:
        clock = VideoClock(
            spans=(
                ActiveSpan(session_from_s=0.0, session_to_s=2.0, video_from_s=0.0, video_to_s=2.0),
                ActiveSpan(session_from_s=30.0, session_to_s=60.0, video_from_s=2.0, video_to_s=32.0),
            )
        )
        resolved = resolve_chapters([_chapter(0, "Loads"), _chapter(3, "Buys")], 60_000, clock)
        assert [(c.start_ms, c.end_ms, c.title) for c in resolved] == [(0, 2_000, "Loads"), (30_000, 60_000, "Buys")]

    def test_a_cut_that_costs_a_video_frame_still_ends_the_chapter_where_the_user_went_idle(self) -> None:
        clock = VideoClock(
            spans=(
                ActiveSpan(session_from_s=0.0, session_to_s=58.0, video_from_s=0.0, video_to_s=58.0),
                ActiveSpan(session_from_s=62.0, session_to_s=80.0, video_from_s=59.0, video_to_s=77.0),
            )
        )
        resolved = resolve_chapters([_chapter(0, "Browses", 58), _chapter(60, "Buys")], 80_000, clock)
        assert [(c.start_ms, c.end_ms) for c in resolved] == [(0, 58_000), (62_000, 80_000)]
        # Video second 58 is where the user went idle, the first chapter's exclusive end, so the frame falls back.
        assert resolved[0].thumbnail_ms == 29_500

    @parameterized.expand(
        [
            (
                "a boundary near a cut snaps onto it, so the inactive time falls between chapters",
                [_chapter(0, "Opens the app", 10), _chapter(30, "Edits a form", 40), _chapter(60, "Saves", 70)],
                [
                    (0, 30_000, "Opens the app", 10_000),
                    (30_000, 58_000, "Edits a form", 40_000),
                    (62_000, 80_000, "Saves", 74_000),
                ],
            ),
            (
                "a boundary just before a cut snaps onto it too",
                [_chapter(0, "Browses"), _chapter(56, "Buys")],
                [(0, 58_000, "Browses", 29_000), (62_000, 80_000, "Buys", 71_000)],
            ),
            (
                "a boundary far from a cut stays, and the inactive time sits inside its chapter",
                [_chapter(0, "Browses"), _chapter(52, "Buys")],
                [(0, 52_000, "Browses", 26_000), (52_000, 80_000, "Buys", 68_000)],
            ),
            (
                "out of order input is sorted and a repeated start keeps the first chapter",
                [_chapter(30, "Second"), _chapter(0, "First"), _chapter(30, "Duplicate")],
                [(0, 30_000, "First", 15_000), (30_000, 80_000, "Second", 53_000)],
            ),
            (
                "the first chapter starts at the start of the video even when the model skipped the page load",
                [_chapter(5, "Only part", 20)],
                [(0, 80_000, "Only part", 20_000)],
            ),
            (
                "a start at or past the video's end is invented and dropped",
                [_chapter(0, "Real"), _chapter(76, "Invented"), _chapter(900, "Invented")],
                [(0, 80_000, "Real", 38_000)],
            ),
            (
                "a thumbnail outside its chapter falls back to the midpoint",
                [_chapter(0, "Browses", 50), _chapter(30, "Buys")],
                [(0, 30_000, "Browses", 15_000), (30_000, 80_000, "Buys", 53_000)],
            ),
            (
                "malformed chapters are dropped and negative starts clamp to 0",
                [
                    SummaryChapterResponse(title="No start"),
                    _chapter(-9, "Opens"),
                    _chapter(-2, "Also opens"),
                    _chapter(30, "(t 30)"),
                    _chapter(40, "Buys"),
                ],
                [(0, 40_000, "Opens", 20_000), (40_000, 80_000, "Buys", 62_000)],
            ),
            ("no chapters stay no chapters", [], []),
        ]
    )
    def test_the_models_chapters_are_repaired_onto_the_session_clock(
        self, _label: str, chapters: list[SummaryChapterResponse], expected: list[tuple[int, int, str, int]]
    ) -> None:
        clock = video_clock_from_export_context({"inactivity_periods": _PERIODS})
        assert clock is not None
        resolved = resolve_chapters(chapters, 80_000, clock)
        assert [(c.start_ms, c.end_ms, c.title, c.thumbnail_ms) for c in resolved] == expected
