from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.ml_inference.backend.facade.contracts import (
    DecisionRequest,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)
from products.replay_vision.backend.jev_watch_feed import (
    WINDOW_CHUNK_SIZE,
    WindowJudgment,
    judge_scanner_window,
    load_watch_ranks,
    rank_watch_feed_by_jev,
    store_watch_ranks,
    watch_feed_ranker,
)
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal.jev_watch_rank.activities import _judge_watch_ranks
from products.replay_vision.backend.temporal.jev_watch_rank.types import JevWatchRankSweepInputs
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for

_FLAG = "products.replay_vision.backend.jev_watch_feed.get_feature_flag_or_none"
_API = "products.replay_vision.backend.jev_watch_feed.decision_api"


def _answer_every_question(probability: float):
    """A decide_when_available side effect that answers each question in the request with `probability`."""

    def _decide(request: DecisionRequest, **kwargs: Any) -> DecisionResult:
        return DecisionResult(
            model="jevk5-fp8-0.2",
            answers={name: NoulAnswer(probability=probability) for name in request.questions},
            input_tokens=120,
        )

    return _decide


def _prose_row(observation_id: object, summary: str) -> dict[str, Any]:
    return {
        "id": observation_id,
        "scanner_result": {
            "model_output": {"scanner_type": "summarizer", "title": "t", "summary": summary, "confidence": 0.9},
            "signals_count": 0,
        },
    }


class TestWatchFeedRankerFlag(SimpleTestCase):
    @parameterized.expand(
        [
            ("flag_off", None, "weighted-score"),
            ("boolean_flag", True, "weighted-score"),
            ("unknown_variant", "something-else", "weighted-score"),
            ("shadow", "jev-shadow", "jev-shadow"),
            ("graduated", "jev", "jev"),
        ]
    )
    def test_only_known_variants_leave_the_default_arm(self, _name: str, flag_value: object, expected: str) -> None:
        with patch(_FLAG, return_value=flag_value):
            assert watch_feed_ranker(1) == expected


class TestJudgeScannerWindow(SimpleTestCase):
    def test_a_window_larger_than_one_chunk_is_judged_across_requests(self) -> None:
        rows = [_prose_row(uuid4(), f"summary {index}") for index in range(WINDOW_CHUNK_SIZE + 6)]
        with patch(_API) as api:
            api.decide_when_available.side_effect = _answer_every_question(0.7)
            judgment = judge_scanner_window(1, uuid4(), rows)
        assert api.decide_when_available.call_count == 2
        assert judgment.chunks == 2
        assert judgment.failed_chunks == 0
        assert len(judgment.probabilities) == len(rows)
        assert judgment.probabilities[str(rows[0]["id"])] == 0.7
        assert judgment.input_tokens == 240
        first_request = api.decide_when_available.call_args_list[0].args[0]
        # The chunk travels as shared state with one question per observation, so each judgment is
        # relative to its siblings.
        assert len(first_request.state["observations"]) == WINDOW_CHUNK_SIZE
        assert len(first_request.questions) == WINDOW_CHUNK_SIZE
        assert "0" in first_request.questions["watch_0"].instructions

    def test_a_failed_chunk_loses_only_its_own_rows(self) -> None:
        rows = [_prose_row(uuid4(), f"summary {index}") for index in range(WINDOW_CHUNK_SIZE + 6)]
        answer = _answer_every_question(0.7)
        attempts: list[int] = []

        def _first_chunk_fails(request: DecisionRequest, **kwargs: Any) -> DecisionResult:
            attempts.append(1)
            if len(attempts) == 1:
                raise DecisionsDisabledError(1)
            return answer(request)

        with patch(_API) as api:
            api.decide_when_available.side_effect = _first_chunk_fails
            judgment = judge_scanner_window(1, uuid4(), rows)
        assert judgment.failed_chunks == 1
        assert len(judgment.probabilities) == 6

    def test_an_invalid_probability_fails_the_whole_chunk(self) -> None:
        rows = [_prose_row(uuid4(), "summary")]
        with patch(_API) as api:
            api.decide_when_available.side_effect = _answer_every_question(7.0)
            judgment = judge_scanner_window(1, uuid4(), rows)
        assert judgment.probabilities == {}
        assert judgment.failed_chunks == 1

    def test_rows_without_prose_are_not_sent(self) -> None:
        rows = [
            _prose_row(uuid4(), "summary"),
            {"id": uuid4(), "scanner_result": {"model_output": {}, "signals_count": 0}},
            {"id": uuid4(), "scanner_result": None},
        ]
        with patch(_API) as api:
            api.decide_when_available.side_effect = _answer_every_question(0.5)
            judgment = judge_scanner_window(1, uuid4(), rows)
        assert len(judgment.probabilities) == 1

    def test_an_empty_window_makes_no_request(self) -> None:
        with patch(_API) as api:
            judgment = judge_scanner_window(1, uuid4(), [])
        api.decide_when_available.assert_not_called()
        assert judgment.probabilities == {}


def _feed_row(observation_id: str, minutes_ago: int, *, viewed: bool = False) -> dict[str, Any]:
    return {
        "id": observation_id,
        "created_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC) - timedelta(minutes=minutes_ago),
        "feed_viewed": viewed,
    }


class TestRankWatchFeedByJev(SimpleTestCase):
    def test_judged_rows_rank_by_probability_and_unjudged_rows_follow_by_recency(self) -> None:
        ranked = rank_watch_feed_by_jev(
            [
                _feed_row("old-unjudged", 50),
                _feed_row("low", 40),
                _feed_row("high", 30),
                _feed_row("new-unjudged", 10),
            ],
            {"low": 0.2, "high": 0.9},
        )
        assert [entry.observation_id for entry in ranked] == ["high", "low", "new-unjudged", "old-unjudged"]
        assert ranked[0].reason == {"kind": "jev_watchable", "jev_probability": 0.9}
        assert ranked[2].reason == {"kind": "unviewed_recent"}

    def test_a_viewed_row_is_docked_but_a_strong_one_still_ranks(self) -> None:
        ranked = rank_watch_feed_by_jev(
            [
                _feed_row("viewed-strong", 30, viewed=True),
                _feed_row("unviewed-mid", 20),
                _feed_row("unviewed-weak", 10),
                _feed_row("viewed-filler", 5, viewed=True),
                _feed_row("unviewed-filler", 1),
            ],
            {"viewed-strong": 0.95, "unviewed-mid": 0.5, "unviewed-weak": 0.3},
        )
        # 0.95 - 0.3 dock = 0.65 still beats 0.5; the weak 0.3 row does not overtake either.
        assert [entry.observation_id for entry in ranked] == [
            "viewed-strong",
            "unviewed-mid",
            "unviewed-weak",
            "unviewed-filler",
            "viewed-filler",
        ]
        assert ranked[3].reason == {"kind": "unviewed_recent"}
        assert ranked[4].reason == {"kind": "recent"}


class TestWatchRankCache(SimpleTestCase):
    def test_stored_ranks_round_trip_and_malformed_values_are_dropped_or_clamped(self) -> None:
        team_id = 990_001
        scanner_id, other_scanner_id, missing_scanner_id = uuid4(), uuid4(), uuid4()
        store_watch_ranks(
            team_id,
            scanner_id,
            WindowJudgment(
                probabilities={"obs-a": 0.9, "obs-b": 7.0},
                model="jevk5-fp8-0.2",
                chunks=1,
                failed_chunks=0,
                input_tokens=10,
                estimated_cost_usd=0.0,
            ),
        )
        store_watch_ranks(
            team_id,
            other_scanner_id,
            WindowJudgment(
                probabilities={"obs-c": 0.4},
                model="jevk5-fp8-0.2",
                chunks=1,
                failed_chunks=0,
                input_tokens=10,
                estimated_cost_usd=0.0,
            ),
        )
        loaded = load_watch_ranks(team_id, [scanner_id, other_scanner_id, missing_scanner_id])
        assert loaded == {"obs-a": 0.9, "obs-b": 1.0, "obs-c": 0.4}
        # Another team's cache never leaks in.
        assert load_watch_ranks(team_id + 1, [scanner_id]) == {}


class TestJevWatchRankSweep(BaseTest):
    def _succeeded_observation(self, scanner: ReplayScanner, session_id: str, summary: str) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={
                "model_output": {"scanner_type": "summarizer", "title": "t", "summary": summary, "confidence": 0.9},
                "signals_count": 0,
            },
        )

    def test_the_sweep_judges_enrolled_teams_and_fills_the_cache(self) -> None:
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="s",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "p", "length": "short"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        first = self._succeeded_observation(scanner, "s1", "The user hit an error at checkout.")
        second = self._succeeded_observation(scanner, "s2", "The user skimmed the pricing page.")

        flag = "products.replay_vision.backend.temporal.jev_watch_rank.activities.watch_feed_ranker"
        with patch(flag, return_value="weighted-score"), patch(_API) as api:
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        # A team on the default arm costs no Jev calls and gets no cache entry.
        api.decide_when_available.assert_not_called()
        assert result.teams_enrolled == 0
        assert load_watch_ranks(self.team.id, [scanner.id]) == {}

        with patch(flag, return_value="jev-shadow"), patch(_API) as api, patch("posthoganalytics.capture"):
            api.decide_when_available.side_effect = _answer_every_question(0.7)
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        assert result.teams_enrolled == 1
        assert result.scanners_judged == 1
        assert result.observations_judged == 2
        assert load_watch_ranks(self.team.id, [scanner.id]) == {str(first.id): 0.7, str(second.id): 0.7}
