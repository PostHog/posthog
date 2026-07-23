from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import MagicMock, patch

from posthog.models.scoping import team_scope

from products.outcomes.backend.models import Outcome, OutcomeLatch
from products.outcomes.backend.tasks import calculate_outcome

from .test_criteria import atom, criteria, path


@patch("products.outcomes.backend.evaluation.capture_batch_internal", return_value=MagicMock())
class TestOutcomeEvaluation(ClickhouseTestMixin, BaseTest):
    def _create_outcome(self, criteria_dict: dict, name: str = "Activated") -> Outcome:
        with team_scope(self.team.id):
            return Outcome.objects.create(team=self.team, created_by=self.user, name=name, criteria=criteria_dict)

    def _calculate(self, outcome: Outcome) -> None:
        calculate_outcome(outcome_id=str(outcome.id), team_id=self.team.id)

    def _latches(self) -> list[OutcomeLatch]:
        return list(OutcomeLatch.objects.for_team(self.team.id))

    def test_and_path_latches_at_last_condition_with_deterministic_reached_at(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_person(distinct_ids=["p2"], team=self.team)
        for ts in ["2026-01-01T10:00:00Z", "2026-01-02T10:00:00Z", "2026-01-03T10:00:00Z"]:
            _create_event(event="uploaded_file", distinct_id="p1", team=self.team, timestamp=ts)
        _create_event(event="invited_teammate", distinct_id="p1", team=self.team, timestamp="2026-01-01T12:00:00Z")
        # p2 uploads twice but never invites: AND must not latch them.
        _create_event(event="uploaded_file", distinct_id="p2", team=self.team, timestamp="2026-01-01T09:00:00Z")
        _create_event(event="uploaded_file", distinct_id="p2", team=self.team, timestamp="2026-01-01T09:30:00Z")

        outcome = self._create_outcome(criteria(path(atom("uploaded_file", threshold=2), atom("invited_teammate"))))
        self._calculate(outcome)

        latches = self._latches()
        assert [latch.distinct_id for latch in latches] == ["p1"]
        # The 2nd upload (Jan 2) completed the upload atom after the invite (Jan 1):
        # the path completes at its last-completing condition.
        assert latches[0].reached_at == datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
        assert latches[0].evidence["winning_path"] == 0
        atoms_evidence = latches[0].evidence["paths"][0]["atoms"]
        assert [a["attained"] for a in atoms_evidence] == [3.0, 1.0]

        mock_capture.assert_called_once()
        emitted = mock_capture.call_args.kwargs["events"]
        assert [e["distinct_id"] for e in emitted] == ["p1"]
        assert emitted[0]["properties"]["backfilled"] is True
        assert emitted[0]["properties"]["evidence"]["winning_path"] == 0

        # Re-evaluation converges: nothing new latches, nothing re-emits.
        self._calculate(outcome)
        assert len(self._latches()) == 1
        mock_capture.assert_called_once()

    def test_or_paths_record_earliest_winning_path(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_event(event="shared_link", distinct_id="p1", team=self.team, timestamp="2026-01-05T10:00:00Z")

        outcome = self._create_outcome(criteria(path(atom("uploaded_file", threshold=5)), path(atom("shared_link"))))
        self._calculate(outcome)

        latches = self._latches()
        assert len(latches) == 1
        assert latches[0].reached_at == datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
        assert latches[0].evidence["winning_path"] == 1
        assert latches[0].evidence["paths"][0]["satisfied"] is False
        assert latches[0].evidence["paths"][1]["satisfied"] is True

    def test_m_of_n_path_latches_at_mth_condition(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_event(event="a", distinct_id="p1", team=self.team, timestamp="2026-01-03T10:00:00Z")
        _create_event(event="c", distinct_id="p1", team=self.team, timestamp="2026-01-01T10:00:00Z")

        outcome = self._create_outcome(criteria(path(atom("a"), atom("b"), atom("c"), min_matches=2)))
        self._calculate(outcome)

        latches = self._latches()
        assert len(latches) == 1
        # Conditions a (Jan 3) and c (Jan 1) are satisfied; the 2nd one to complete was a.
        assert latches[0].reached_at == datetime(2026, 1, 3, 10, 0, tzinfo=UTC)

    def test_sum_aggregation_crosses_at_cumulative_threshold(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_person(distinct_ids=["p2"], team=self.team)
        for ts, amount in [("2026-01-01T10:00:00Z", 40), ("2026-01-02T10:00:00Z", 70), ("2026-01-03T10:00:00Z", 5)]:
            _create_event(
                event="purchase", distinct_id="p1", team=self.team, timestamp=ts, properties={"amount": amount}
            )
        _create_event(
            event="purchase",
            distinct_id="p2",
            team=self.team,
            timestamp="2026-01-01T10:00:00Z",
            properties={"amount": 40},
        )

        outcome = self._create_outcome(
            criteria(path(atom("purchase", aggregation="sum", aggregation_property="amount", threshold=100)))
        )
        self._calculate(outcome)

        latches = self._latches()
        assert [latch.distinct_id for latch in latches] == ["p1"]
        # The running sum (40, 110, 115) crossed 100 on the second purchase.
        assert latches[0].reached_at == datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
        assert latches[0].evidence["paths"][0]["atoms"][0]["attained"] == 115.0

    def test_distinct_aggregation_crosses_at_nth_distinct_value(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        for ts, file_type in [
            ("2026-01-01T10:00:00Z", "pdf"),
            ("2026-01-02T10:00:00Z", "pdf"),
            ("2026-01-03T10:00:00Z", "png"),
            ("2026-01-04T10:00:00Z", "gif"),
        ]:
            _create_event(
                event="uploaded_file",
                distinct_id="p1",
                team=self.team,
                timestamp=ts,
                properties={"file_type": file_type},
            )

        outcome = self._create_outcome(
            criteria(path(atom("uploaded_file", aggregation="distinct", aggregation_property="file_type", threshold=2)))
        )
        self._calculate(outcome)

        latches = self._latches()
        assert len(latches) == 1
        # The 2nd distinct file type (png) first appeared on Jan 3.
        assert latches[0].reached_at == datetime(2026, 1, 3, 10, 0, tzinfo=UTC)
        assert latches[0].evidence["paths"][0]["atoms"][0]["attained"] == 3.0

    def test_property_filters_scope_the_atom(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_person(distinct_ids=["p2"], team=self.team)
        _create_event(
            event="signed_up",
            distinct_id="p1",
            team=self.team,
            timestamp="2026-01-01T10:00:00Z",
            properties={"plan": "pro"},
        )
        _create_event(
            event="signed_up",
            distinct_id="p2",
            team=self.team,
            timestamp="2026-01-01T10:00:00Z",
            properties={"plan": "free"},
        )

        outcome = self._create_outcome(
            criteria(path(atom("signed_up", properties=[{"key": "plan", "value": "pro", "type": "event"}])))
        )
        self._calculate(outcome)

        assert [latch.distinct_id for latch in self._latches()] == ["p1"]

    def test_only_new_reachers_emit_on_later_runs_and_are_not_backfilled(self, mock_capture: MagicMock) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        _create_event(event="signed_up", distinct_id="p1", team=self.team, timestamp="2026-01-01T10:00:00Z")
        outcome = self._create_outcome(criteria(path(atom("signed_up"))))

        self._calculate(outcome)
        assert len(self._latches()) == 1

        _create_person(distinct_ids=["p2"], team=self.team)
        _create_event(event="signed_up", distinct_id="p2", team=self.team, timestamp="2026-01-05T10:00:00Z")

        self._calculate(outcome)

        assert len(self._latches()) == 2
        assert mock_capture.call_count == 2
        second_run_events = mock_capture.call_args.kwargs["events"]
        assert [e["distinct_id"] for e in second_run_events] == ["p2"]
        assert second_run_events[0]["properties"]["backfilled"] is False

    def test_invalid_stored_criteria_skip_evaluation(self, mock_capture: MagicMock) -> None:
        # Serializer validation guards the API, but a stored definition could still be
        # corrupt (or predate stricter rules): the evaluator must skip it, not crash or latch.
        outcome = self._create_outcome(criteria(path(atom("$outcome_reached"))))

        self._calculate(outcome)

        assert self._latches() == []
        mock_capture.assert_not_called()
