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
    judge_scanner_window,
    load_judged_ids,
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

    def test_rows_without_prose_are_reported_instead_of_sent(self) -> None:
        no_output, no_result = uuid4(), uuid4()
        rows = [
            _prose_row(uuid4(), "summary"),
            {"id": no_output, "scanner_result": {"model_output": {}, "signals_count": 0}},
            {"id": no_result, "scanner_result": None},
        ]
        with patch(_API) as api:
            api.decide_when_available.side_effect = _answer_every_question(0.5)
            judgment = judge_scanner_window(1, uuid4(), rows)
        assert len(judgment.probabilities) == 1
        assert set(judgment.skipped_no_prose) == {str(no_output), str(no_result)}

    def test_context_rows_enter_the_state_without_questions(self) -> None:
        rows = [_prose_row(uuid4(), f"new {index}") for index in range(3)]
        context_rows = [_prose_row(uuid4(), f"old {index}") for index in range(40)]
        with patch(_API) as api:
            api.decide_when_available.side_effect = _answer_every_question(0.5)
            judgment = judge_scanner_window(1, uuid4(), rows, context_rows)
        request = api.decide_when_available.call_args.args[0]
        # A quiet hour's small batch is still judged against the scanner's routine, and the state
        # never exceeds one chunk's size.
        assert len(request.questions) == 3
        assert len(request.state["observations"]) == WINDOW_CHUNK_SIZE
        assert len(judgment.probabilities) == 3

    def test_long_prose_is_clipped_before_it_enters_the_request(self) -> None:
        rows = [_prose_row(uuid4(), "x" * 100_000)]
        with patch(_API) as api:
            api.decide_when_available.side_effect = _answer_every_question(0.5)
            judge_scanner_window(1, uuid4(), rows)
        request = api.decide_when_available.call_args.args[0]
        assert len(request.state["observations"]["0"]["summary"]) == 1500

    def test_an_empty_window_makes_no_request(self) -> None:
        with patch(_API) as api:
            judgment = judge_scanner_window(1, uuid4(), [])
        api.decide_when_available.assert_not_called()
        assert judgment.probabilities == {}


def _feed_row(
    observation_id: str,
    minutes_ago: int,
    *,
    viewed: bool = False,
    scanner: str = "scanner-a",
    notability: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": observation_id,
        "scanner_id": scanner,
        "created_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC) - timedelta(minutes=minutes_ago),
        "feed_viewed": viewed,
    }
    if notability is not None:
        row["scanner_result"] = {"model_output": {"notability_reason": notability}}
    return row


class TestRankWatchFeedByJev(SimpleTestCase):
    def test_watchable_rows_rank_by_probability_and_the_rest_follow_by_recency(self) -> None:
        # A judged-low row falls to the same recency filler tier as an unjudged one, so a stale low
        # judgment never outranks a fresh observation the sweep has not seen yet, and its card never
        # claims the model judged it worth watching.
        ranked = rank_watch_feed_by_jev(
            [
                _feed_row("old-unjudged", 50),
                _feed_row("judged-low", 40),
                _feed_row("high", 30),
                _feed_row("higher", 20, notability="The user paid twice for one order."),
                _feed_row("new-unjudged", 10),
            ],
            {"judged-low": 0.2, "high": 0.7, "higher": 0.9},
        )
        assert [entry.observation_id for entry in ranked] == [
            "higher",
            "high",
            "new-unjudged",
            "judged-low",
            "old-unjudged",
        ]
        # The scan's own sentence rides along so the card can explain the pick; a row without one
        # carries only the kind and probability.
        assert ranked[0].reason == {
            "kind": "jev_watchable",
            "jev_probability": 0.9,
            "notability_reason": "The user paid twice for one order.",
        }
        assert ranked[1].reason == {"kind": "jev_watchable", "jev_probability": 0.7}
        assert ranked[2].reason == {"kind": "unviewed_recent"}
        assert ranked[3].reason == {"kind": "unviewed_recent"}

    def test_one_scanner_cannot_flood_the_top_of_the_evidence_tier(self) -> None:
        # One incident's near-identical sessions must leave room for other scanners' findings, and
        # the overflow trails the tier instead of dropping out of it.
        rows = [_feed_row(f"flood-{index}", 10 + index, scanner="flooding") for index in range(6)]
        rows += [_feed_row("other-0", 30, scanner="quiet"), _feed_row("other-1", 31, scanner="quiet")]
        probabilities = {f"flood-{index}": 0.96 - index / 100 for index in range(6)} | {
            "other-0": 0.7,
            "other-1": 0.69,
        }
        ranked = rank_watch_feed_by_jev(rows, probabilities)
        assert [entry.observation_id for entry in ranked] == [
            "flood-0",
            "flood-1",
            "flood-2",
            "other-0",
            "other-1",
            "flood-3",
            "flood-4",
            "flood-5",
        ]

    def test_a_viewed_row_is_docked_inside_the_watchable_tier_only(self) -> None:
        ranked = rank_watch_feed_by_jev(
            [
                _feed_row("viewed-strong", 30, viewed=True),
                _feed_row("unviewed-mid", 20),
                # Raw probability decides the tier, so the dock cannot push a watchable row into filler.
                _feed_row("viewed-borderline", 15, viewed=True),
                _feed_row("viewed-filler", 5, viewed=True),
                _feed_row("unviewed-filler", 1),
            ],
            {"viewed-strong": 0.95, "unviewed-mid": 0.6, "viewed-borderline": 0.55},
        )
        # 0.95 - 0.3 dock = 0.65 still beats 0.6; 0.55 - 0.3 = 0.25 stays watchable, ordered last.
        assert [entry.observation_id for entry in ranked] == [
            "viewed-strong",
            "unviewed-mid",
            "viewed-borderline",
            "unviewed-filler",
            "viewed-filler",
        ]
        assert ranked[2].reason == {"kind": "jev_watchable", "jev_probability": 0.55}
        assert ranked[3].reason == {"kind": "unviewed_recent"}
        assert ranked[4].reason == {"kind": "recent"}


class TestWatchRankCache(SimpleTestCase):
    def test_stored_ranks_round_trip_and_malformed_values_are_dropped_or_clamped(self) -> None:
        team_id = 990_001
        scanner_id, other_scanner_id, missing_scanner_id = uuid4(), uuid4(), uuid4()
        store_watch_ranks(team_id, scanner_id, {"obs-a", "obs-b", "obs-low"}, {"obs-a": 0.9, "obs-b": 7.0}, "jevk5")
        store_watch_ranks(team_id, other_scanner_id, {"obs-c"}, {"obs-c": 0.4}, "jevk5")
        loaded = load_watch_ranks(team_id, [scanner_id, other_scanner_id, missing_scanner_id])
        assert loaded == {"obs-a": 0.9, "obs-b": 1.0, "obs-c": 0.4}
        # The feed's per-request keys carry only the watchable map; the judged set remembers every
        # row the sweep has bought, including the sub-threshold ones the feed never needs.
        assert load_judged_ids(team_id, scanner_id) == {"obs-a", "obs-b", "obs-low"}
        assert load_judged_ids(team_id, missing_scanner_id) == set()
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

    def test_the_sweep_gates_judges_and_skips_unchanged_windows(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="s",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "p", "length": "short"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        first = self._succeeded_observation(scanner, "s1", "The user hit an error at checkout.")
        second = self._succeeded_observation(scanner, "s2", "The user skimmed the pricing page.")

        activities = "products.replay_vision.backend.temporal.jev_watch_rank.activities"
        flag = f"{activities}.watch_feed_ranker"
        region = f"{activities}.decision_api.decisions_available_here"

        with patch(flag, return_value="weighted-score"), patch(region, return_value=True), patch(_API) as api:
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        # A team on the default arm costs no Jev calls and gets no cache entry.
        api.decide_when_available.assert_not_called()
        assert result.teams_enrolled == 0
        assert load_watch_ranks(self.team.id, [scanner.id]) == {}

        with patch(flag, return_value="jev-shadow"), patch(region, return_value=False), patch(_API) as api:
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        # A region without the decision service does no work at all.
        api.decide_when_available.assert_not_called()
        assert result.decisions_unavailable

        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        with patch(flag, return_value="jev-shadow"), patch(region, return_value=True), patch(_API) as api:
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        # An enrolled team without AI data-processing consent sends nothing to the model.
        api.decide_when_available.assert_not_called()
        assert result.teams_without_consent == 1
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        with (
            patch(flag, return_value="jev-shadow"),
            patch(region, return_value=True),
            patch(_API) as api,
            patch("posthoganalytics.capture"),
        ):
            api.decide_when_available.side_effect = _answer_every_question(0.7)
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        assert result.teams_enrolled == 1
        assert result.scanners_judged == 1
        assert result.observations_judged == 2
        assert load_watch_ranks(self.team.id, [scanner.id]) == {str(first.id): 0.7, str(second.id): 0.7}

        with patch(flag, return_value="jev-shadow"), patch(region, return_value=True), patch(_API) as api:
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        # Every row is judged already, so the second run keeps the cache without a Jev call.
        api.decide_when_available.assert_not_called()
        assert result.scanners_skipped_unchanged == 1
        assert load_watch_ranks(self.team.id, [scanner.id]) == {str(first.id): 0.7, str(second.id): 0.7}

        third = self._succeeded_observation(scanner, "s3", "The user deleted the whole workspace.")
        with (
            patch(flag, return_value="jev-shadow"),
            patch(region, return_value=True),
            patch(_API) as api,
            patch("posthoganalytics.capture"),
        ):
            api.decide_when_available.side_effect = _answer_every_question(0.9)
            result = async_to_sync(_judge_watch_ranks)(JevWatchRankSweepInputs())
        # Only the new row is judged, with the already-judged rows in the state as context, and the
        # earlier judgments survive the merge.
        request = api.decide_when_available.call_args.args[0]
        assert len(request.questions) == 1
        assert len(request.state["observations"]) == 3
        assert result.observations_judged == 1
        assert load_watch_ranks(self.team.id, [scanner.id]) == {
            str(first.id): 0.7,
            str(second.id): 0.7,
            str(third.id): 0.9,
        }
