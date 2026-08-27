from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.utils import uuid7

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_alert import (
    VisionAlertConfiguration,
    VisionAlertKind,
    VisionAlertMatch,
)
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_ineligible_activity,
    mark_observation_succeeded_activity,
)
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.types import (
    MarkObservationFailedInputs,
    MarkObservationIneligibleInputs,
    MarkObservationSucceededInputs,
    ScannerResult,
)
from products.replay_vision.backend.temporal.vision_alerts.activities import (
    CleanupAlertHistoryInput,
    DrainMatchesInput,
    _cleanup_history,
    _drain_matches,
)
from products.replay_vision.backend.temporal.vision_alerts.constants import MATCH_SUMMARY_LINES
from products.replay_vision.backend.temporal.vision_alerts.match_hook import selection_matches
from products.replay_vision.backend.tests.helpers import snapshot_for

_ACTIVITIES = "products.replay_vision.backend.temporal.vision_alerts.activities"


class TestVisionAlertMatchOutbox(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )

    def _make_match_alert(self, **overrides: Any) -> VisionAlertConfiguration:
        fields: dict[str, Any] = {
            "team": self.team,
            "scanner": self.scanner,
            "name": f"match-{uuid7()}",
            "kind": VisionAlertKind.MATCH,
            "selection": {"verdict": ["yes"]},
            "first_enabled_at": timezone.now(),
        }
        fields.update(overrides)
        return VisionAlertConfiguration.objects.for_team(self.team.id).create(**fields)

    def _make_pending_observation(self) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=f"s-{uuid7()}",
            status=ObservationStatus.RUNNING,
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )

    def _succeed(self, observation: ReplayObservation, verdict: str = "yes") -> None:
        result = ScannerResult(
            model_output=MonitorOutput(
                scanner_type=ScannerType.MONITOR,
                verdict=verdict,
                reasoning="checkout broke",
                confidence=0.9,
            )
        )
        with patch("products.replay_vision.backend.temporal.activities.observation_state.posthoganalytics"):
            mark_observation_succeeded_activity(
                MarkObservationSucceededInputs(
                    observation_id=observation.id, scanner_type=ScannerType.MONITOR, scanner_result=result
                )
            )

    def _outbox_rows(self) -> list[VisionAlertMatch]:
        return list(VisionAlertMatch.all_teams.filter(team_id=self.team.id))

    def test_succeeded_observation_inserts_one_row_per_matching_alert(self) -> None:
        matching = self._make_match_alert()
        self._make_match_alert(name="second matcher", selection={})
        self._make_match_alert(name="wrong verdict", selection={"verdict": ["no"]})
        self._make_match_alert(name="disabled", enabled=False)

        observation = self._make_pending_observation()
        self._succeed(observation)

        rows = self._outbox_rows()
        alert_names = {VisionAlertConfiguration.all_teams.get(id=row.alert_id).name for row in rows}
        assert matching.name in alert_names
        assert "second matcher" in alert_names
        assert len(rows) == 2
        assert all(row.observation_id == observation.id and row.delivered_at is None for row in rows)

    def test_retry_after_transition_inserts_nothing(self) -> None:
        self._make_match_alert(selection={})
        observation = self._make_pending_observation()
        self._succeed(observation)
        assert len(self._outbox_rows()) == 1
        self._succeed(observation)
        assert len(self._outbox_rows()) == 1

    def test_failed_observation_inserts_nothing(self) -> None:
        self._make_match_alert(name="catch all", selection={})

        observation = self._make_pending_observation()
        mark_observation_failed_activity(
            MarkObservationFailedInputs(
                observation_id=observation.id, scanner_type=ScannerType.MONITOR, error_reason="provider_error:boom"
            )
        )

        assert self._outbox_rows() == []

    def test_ineligible_observation_inserts_nothing(self) -> None:
        self._make_match_alert(selection={})
        observation = self._make_pending_observation()
        mark_observation_ineligible_activity(
            MarkObservationIneligibleInputs(
                observation_id=observation.id, scanner_type=ScannerType.MONITOR, error_reason="no_recording:none"
            )
        )
        assert self._outbox_rows() == []

    def _drain(self, *, delivered: bool = True, produce_side_effect: Any = None):
        produce_result = MagicMock()
        with (
            patch(
                f"{_ACTIVITIES}.produce_alert_internal_event",
                return_value=produce_result,
                side_effect=produce_side_effect,
            ) as produce,
            patch(f"{_ACTIVITIES}.flush_alert_internal_events"),
            patch(f"{_ACTIVITIES}.alert_internal_event_delivered", return_value=delivered),
        ):
            output = _drain_matches(DrainMatchesInput())
        return output, produce

    def test_drain_bundles_and_stamps_only_after_ack(self) -> None:
        alert = self._make_match_alert(selection={})
        for _ in range(3):
            self._succeed(self._make_pending_observation())

        output, produce = self._drain(delivered=True)
        assert output.alerts_notified == 1
        assert output.matches_delivered == 3
        assert produce.call_count == 1
        props = produce.call_args.kwargs["properties"]
        assert props["matched_count"] == 3
        assert len(props["observation_ids"]) == 3
        assert props["summary"].count("verdict=yes") == 3
        assert produce.call_args.kwargs["uuid"] is not None
        assert not VisionAlertMatch.all_teams.filter(alert_id=alert.id, delivered_at__isnull=True).exists()

        # Nothing pending -> next drain emits nothing.
        output, produce = self._drain(delivered=True)
        assert produce.call_count == 0

    def test_unacked_bundle_stays_pending_and_retries(self) -> None:
        alert = self._make_match_alert(selection={})
        self._succeed(self._make_pending_observation())

        output, _ = self._drain(delivered=False)
        assert output.alerts_notified == 0
        assert VisionAlertMatch.all_teams.filter(alert_id=alert.id, delivered_at__isnull=True).count() == 1

        output, _ = self._drain(delivered=True)
        assert output.alerts_notified == 1

    def test_mid_drain_insert_is_not_stamped(self) -> None:
        alert = self._make_match_alert(selection={})
        self._succeed(self._make_pending_observation())

        late_observation = self._make_pending_observation()

        def insert_late_row(**kwargs: Any) -> MagicMock:
            # A row landing between the drain read and the stamp must survive it.
            self._succeed(late_observation)
            return MagicMock()

        output, _ = self._drain(delivered=True, produce_side_effect=insert_late_row)
        assert output.matches_delivered == 1
        assert VisionAlertMatch.all_teams.filter(alert_id=alert.id, delivered_at__isnull=True).count() == 1

    def test_drain_skips_disabled_and_holds_snoozed(self) -> None:
        disabled = self._make_match_alert(name="disabled later", selection={})
        snoozed = self._make_match_alert(name="snoozed", selection={})
        for _ in range(2):
            self._succeed(self._make_pending_observation())
        VisionAlertConfiguration.all_teams.filter(id=disabled.id).update(enabled=False)
        VisionAlertConfiguration.all_teams.filter(id=snoozed.id).update(
            snooze_until=datetime.now(UTC) + timedelta(hours=1)
        )

        output, produce = self._drain(delivered=True)
        assert output.alerts_notified == 0
        assert produce.call_count == 0
        assert VisionAlertMatch.all_teams.filter(delivered_at__isnull=True).count() == 4

    def test_summary_caps_lines_but_stamps_all_rows(self) -> None:
        alert = self._make_match_alert(selection={})
        for _ in range(MATCH_SUMMARY_LINES + 2):
            self._succeed(self._make_pending_observation())

        output, produce = self._drain(delivered=True)
        assert output.matches_delivered == MATCH_SUMMARY_LINES + 2
        props = produce.call_args.kwargs["properties"]
        assert f"and 2 more" in props["summary"]
        assert not VisionAlertMatch.all_teams.filter(alert_id=alert.id, delivered_at__isnull=True).exists()

    @parameterized.expand(
        [
            ("min_score_zero_matches_zero", {"min_score": 0}, {"score": 0.0}, True),
            ("min_score_zero_needs_a_score", {"min_score": 0}, {}, False),
            ("max_score_excludes_above", {"max_score": 2}, {"score": 2.5}, False),
            ("legacy_single_verdict_string", {"verdict": "yes"}, {"verdict": "yes"}, True),
            ("verdict_list_excludes_other", {"verdict": ["no"]}, {"verdict": "yes"}, False),
            ("freeform_tag_counts", {"tags": ["checkout"]}, {"tags_freeform": ["checkout"]}, True),
        ]
    )
    def test_selection_matches_semantics(self, _name: str, selection: dict, model_output: dict, expected: bool) -> None:
        assert selection_matches(model_output, selection) is expected

    def test_backlogged_alert_does_not_starve_another_alerts_bundle(self) -> None:
        loud = self._make_match_alert(name="loud", selection={"verdict": ["yes"]})
        quiet = self._make_match_alert(name="quiet", selection={"verdict": ["no"]})
        for _ in range(3):
            self._succeed(self._make_pending_observation(), verdict="yes")
        self._succeed(self._make_pending_observation(), verdict="no")

        with patch(f"{_ACTIVITIES}.MAX_MATCHES_PER_BUNDLE", 2):
            output, produce = self._drain(delivered=True)

        assert output.alerts_notified == 2
        assert output.matches_delivered == 3
        assert produce.call_count == 2
        assert VisionAlertMatch.all_teams.filter(alert_id=loud.id, delivered_at__isnull=True).count() == 1
        assert not VisionAlertMatch.all_teams.filter(alert_id=quiet.id, delivered_at__isnull=True).exists()

    def test_cleanup_reaps_delivered_and_stale_rows(self) -> None:
        self._make_match_alert(selection={})
        self._succeed(self._make_pending_observation())
        self._succeed(self._make_pending_observation())
        rows = VisionAlertMatch.all_teams.filter(team_id=self.team.id)
        old = timezone.now() - timedelta(days=40)
        first, second = list(rows)
        VisionAlertMatch.all_teams.filter(id=first.id).update(delivered_at=old, created_at=old)
        VisionAlertMatch.all_teams.filter(id=second.id).update(created_at=old)

        deleted = _cleanup_history(CleanupAlertHistoryInput())
        assert deleted == 2
        assert not VisionAlertMatch.all_teams.filter(team_id=self.team.id).exists()
