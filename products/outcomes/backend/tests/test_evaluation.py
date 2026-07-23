from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import MagicMock, patch

from posthog.models.scoping import team_scope

from products.outcomes.backend.models import Outcome, OutcomeLatch
from products.outcomes.backend.tasks import calculate_outcome


@patch("products.outcomes.backend.evaluation.capture_batch_internal", return_value=MagicMock())
class TestOutcomeEvaluation(ClickhouseTestMixin, BaseTest):
    def _create_outcome(self, **kwargs) -> Outcome:
        defaults = {"name": "Activated", "target_event": "uploaded_file", "threshold": 2}
        defaults.update(kwargs)
        with team_scope(self.team.id):
            return Outcome.objects.create(team=self.team, created_by=self.user, **defaults)

    def _latches(self) -> list[OutcomeLatch]:
        return list(OutcomeLatch.objects.for_team(self.team.id))

    def test_latches_at_threshold_with_deterministic_reached_at_and_emits_once(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_person(distinct_ids=["p2"], team=self.team)
        for ts in ["2026-01-01T10:00:00Z", "2026-01-02T10:00:00Z", "2026-01-03T10:00:00Z"]:
            _create_event(event="uploaded_file", distinct_id="p1", team=self.team, timestamp=ts)
        _create_event(event="uploaded_file", distinct_id="p2", team=self.team, timestamp="2026-01-01T12:00:00Z")
        _create_event(event="unrelated_event", distinct_id="p2", team=self.team, timestamp="2026-01-02T12:00:00Z")
        outcome = self._create_outcome()

        calculate_outcome(outcome_id=str(outcome.id), team_id=self.team.id)

        latches = self._latches()
        assert len(latches) == 1
        latch = latches[0]
        assert latch.distinct_id == "p1"
        assert latch.event_count == 3
        # reached_at is the second (threshold-crossing) event, not evaluation time.
        assert latch.reached_at == datetime(2026, 1, 2, 10, 0, tzinfo=UTC)

        outcome.refresh_from_db()
        assert outcome.last_calculated_at is not None

        mock_capture.assert_called_once()
        emitted = mock_capture.call_args.kwargs["events"]
        assert len(emitted) == 1
        assert emitted[0]["event"] == "$outcome_reached"
        assert emitted[0]["distinct_id"] == "p1"
        assert emitted[0]["properties"]["backfilled"] is True
        assert emitted[0]["properties"]["event_count"] == 3

        # Re-evaluation converges: nothing new latches, nothing re-emits.
        calculate_outcome(outcome_id=str(outcome.id), team_id=self.team.id)
        assert len(self._latches()) == 1
        mock_capture.assert_called_once()

    def test_only_new_reachers_emit_on_later_runs_and_are_not_backfilled(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_event(event="signed_up", distinct_id="p1", team=self.team, timestamp="2026-01-01T10:00:00Z")
        outcome = self._create_outcome(target_event="signed_up", threshold=1)

        calculate_outcome(outcome_id=str(outcome.id), team_id=self.team.id)
        assert len(self._latches()) == 1

        _create_person(distinct_ids=["p2"], team=self.team)
        _create_event(event="signed_up", distinct_id="p2", team=self.team, timestamp="2026-01-05T10:00:00Z")

        calculate_outcome(outcome_id=str(outcome.id), team_id=self.team.id)

        assert len(self._latches()) == 2
        assert mock_capture.call_count == 2
        second_run_events = mock_capture.call_args.kwargs["events"]
        assert [e["distinct_id"] for e in second_run_events] == ["p2"]
        assert second_run_events[0]["properties"]["backfilled"] is False

    def test_loop_guard_never_evaluates_outcome_reached(self, mock_capture: MagicMock) -> None:
        outcome = self._create_outcome(target_event="$outcome_reached", threshold=1)

        calculate_outcome(outcome_id=str(outcome.id), team_id=self.team.id)

        assert self._latches() == []
        mock_capture.assert_not_called()
