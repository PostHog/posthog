from contextlib import contextmanager
from uuid import uuid4

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from products.subscriptions.backend.pulse import telemetry


class TestPulseTelemetry(SimpleTestCase):
    def test_captures_only_bounded_run_state(self) -> None:
        capture = Mock()

        @contextmanager
        def scoped_capture():
            yield capture

        run_id = uuid4()
        plan_id = uuid4()
        with patch.object(telemetry, "ph_scoped_capture", scoped_capture):
            telemetry.capture_pulse_run_started(team_id=123, run_id=run_id)
            telemetry.capture_pulse_run_terminalized(team_id=123, run_id=run_id, status="completed")
            telemetry.capture_pulse_delivery_prepared(team_id=123, run_id=run_id, destination="email")
            telemetry.capture_pulse_delivery_finished(
                team_id=123, run_id=run_id, destination="email", outcome="accepted"
            )
            telemetry.capture_pulse_outcome(
                team_id=123,
                run_id=run_id,
                event="pulse_outcome_claimed",
                plan_id=plan_id,
                status="claimed",
                count=1,
            )
            telemetry.capture_pulse_outcome(
                team_id=123,
                run_id=run_id,
                event="pulse_outcome_attempted",
                plan_id=plan_id,
                status="measured",
                verdict="improved",
            )
            telemetry.capture_pulse_outcome(
                team_id=123,
                run_id=run_id,
                event="pulse_outcome_attempted",
                plan_id=plan_id,
                status="inconclusive",
                verdict="inconclusive",
                reason="evidence_unavailable",
            )
            telemetry.capture_pulse_outcome(
                team_id=123,
                run_id=run_id,
                event="pulse_outcome_adoption",
                plan_id=plan_id,
                status="adopted",
                delay_days=7,
                source="pull_request_merged",
            )
            telemetry.capture_pulse_outcome(
                team_id=123,
                run_id=run_id,
                event="pulse_outcome_adoption",
                plan_id=plan_id,
                status="abandoned",
                source="experiment_deleted",
            )

        self.assertEqual(
            capture.call_args_list,
            [
                ((), {"distinct_id": "pulse:123", "event": "pulse_run_started", "properties": {"run_id": str(run_id)}}),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_run_terminalized",
                        "properties": {"run_id": str(run_id), "status": "completed"},
                    },
                ),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_delivery_prepared",
                        "properties": {"run_id": str(run_id), "destination": "email"},
                    },
                ),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_delivery_finished",
                        "properties": {
                            "run_id": str(run_id),
                            "destination": "email",
                            "outcome": "accepted",
                        },
                    },
                ),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_outcome_claimed",
                        "properties": {
                            "run_id": str(run_id),
                            "plan_id": str(plan_id),
                            "status": "claimed",
                            "count": 1,
                        },
                    },
                ),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_outcome_attempted",
                        "properties": {
                            "run_id": str(run_id),
                            "plan_id": str(plan_id),
                            "status": "measured",
                            "verdict": "improved",
                        },
                    },
                ),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_outcome_attempted",
                        "properties": {
                            "run_id": str(run_id),
                            "plan_id": str(plan_id),
                            "status": "inconclusive",
                            "verdict": "inconclusive",
                            "reason": "evidence_unavailable",
                        },
                    },
                ),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_outcome_adoption",
                        "properties": {
                            "run_id": str(run_id),
                            "plan_id": str(plan_id),
                            "status": "adopted",
                            "delay_days": 7,
                            "source": "pull_request_merged",
                        },
                    },
                ),
                (
                    (),
                    {
                        "distinct_id": "pulse:123",
                        "event": "pulse_outcome_adoption",
                        "properties": {
                            "run_id": str(run_id),
                            "plan_id": str(plan_id),
                            "status": "abandoned",
                            "source": "experiment_deleted",
                        },
                    },
                ),
            ],
        )

    def test_rejects_unbounded_telemetry_values(self) -> None:
        with self.assertRaises(ValueError):
            telemetry.capture_pulse_run_terminalized(team_id=1, run_id=uuid4(), status="prompt contents")
        with self.assertRaises(ValueError):
            telemetry.capture_pulse_delivery_finished(
                team_id=1, run_id=uuid4(), destination="recipient@example.com", outcome="accepted"
            )
        with self.assertRaises(ValueError):
            telemetry.capture_pulse_outcome(
                team_id=1,
                run_id=uuid4(),
                event="pulse_outcome_attempted",
                verdict="model_authored",
            )
        with self.assertRaises(ValueError):
            telemetry.capture_pulse_outcome(
                team_id=1,
                run_id=uuid4(),
                event="pulse_outcome_attempted",
                reason="raw provider error contents",
            )
        with self.assertRaises(ValueError):
            telemetry.capture_pulse_outcome(
                team_id=1,
                run_id=uuid4(),
                event="pulse_outcome_adoption",
                source="raw webhook payload",
            )

    def test_captures_manual_dismissal(self) -> None:
        capture = Mock()

        @contextmanager
        def scoped_capture():
            yield capture

        run_id = uuid4()
        plan_id = uuid4()
        with patch.object(telemetry, "ph_scoped_capture", scoped_capture):
            telemetry.capture_pulse_outcome(
                team_id=123,
                run_id=run_id,
                event="pulse_outcome_adoption",
                plan_id=plan_id,
                status="dismissed",
                source="manual",
            )

        capture.assert_called_once_with(
            distinct_id="pulse:123",
            event="pulse_outcome_adoption",
            properties={
                "run_id": str(run_id),
                "plan_id": str(plan_id),
                "status": "dismissed",
                "source": "manual",
            },
        )
