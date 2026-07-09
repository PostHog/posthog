from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import (
    ActionMode,
    VisionAction,
    VisionActionRun,
    VisionActionRunStatus,
)
from products.replay_vision.backend.temporal.vision_actions.alerts import _evaluate
from products.replay_vision.backend.temporal.vision_actions.types import AlertStatus, EvaluateAlertInputs
from products.replay_vision.backend.tests.helpers import snapshot_for

DAILY = {"rrule": "FREQ=DAILY", "timezone": "UTC"}


class TestVisionActionAlerts(BaseTest):
    def _scanner(self, scanner_type: str = ScannerType.MONITOR, name: str = "watcher") -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name=name,
            scanner_type=scanner_type,
            scanner_config={"prompt": "watch"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def _observation(
        self, scanner: ReplayScanner, output: dict, session_id: str = "s1", age_days: float = 0
    ) -> ReplayObservation:
        obs = ReplayObservation.objects.create(
            scanner=scanner,
            session_id=session_id,
            scanner_snapshot=snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={"model_output": {"scanner_type": scanner.scanner_type, **output}},
        )
        if age_days:
            # created_at is auto_now_add; backdate via update() for window tests.
            ReplayObservation.objects.filter(pk=obs.pk).update(created_at=timezone.now() - timedelta(days=age_days))
        return obs

    def _alert(self, scanner: ReplayScanner, alert_config: dict, selection: dict | None = None) -> VisionAction:
        action = VisionAction(
            team=self.team,
            name=f"alert-{scanner.name}",
            scanner=scanner,
            created_by=self.user,
            mode=ActionMode.ALERT,
            trigger_config=DAILY,
            selection=selection or {},
            alert_config=alert_config,
        )
        action.save()
        return action

    def _evaluate(self, action: VisionAction, key: str = "k1"):
        run = VisionActionRun(vision_action=action, team=self.team, idempotency_key=key)
        run.save()
        return _evaluate(EvaluateAlertInputs(run_id=run.id, team_id=self.team.id)), run

    def test_count_alert_fires_and_persists_deterministic_message(self) -> None:
        scanner = self._scanner()
        self._observation(scanner, {"verdict": "yes", "reasoning": "user hit the bug"})
        self._observation(scanner, {"verdict": "yes", "reasoning": "again"}, session_id="s2")
        action = self._alert(scanner, {"metric": "count", "operator": "gte", "threshold": 2})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        self.assertEqual(result.observation_count, 2)
        self.assertEqual(result.metric_value, 2.0)
        run.refresh_from_db()
        self.assertIn("Alert: watcher", run.synthesized_markdown)
        self.assertIn("over the last 24 hours", run.synthesized_markdown)
        self.assertIn("at or above the threshold of 2", run.synthesized_markdown)
        self.assertIn("2 observations matched", run.synthesized_markdown)
        self.assertTrue(run.output["slack"])
        self.assertEqual(len(run.observation_ids), 2)

    @parameterized.expand(
        [
            ("gte_below_threshold", "gte", 3, AlertStatus.NOT_BREACHED),
            ("gt_at_threshold", "gt", 2, AlertStatus.NOT_BREACHED),
            ("lt_above_threshold", "lt", 2, AlertStatus.NOT_BREACHED),
            ("lte_at_threshold", "lte", 2, AlertStatus.FIRED),
            ("eq_exact", "eq", 2, AlertStatus.FIRED),
        ]
    )
    def test_operator_semantics_over_count(self, _label: str, op: str, threshold: float, expected: AlertStatus) -> None:
        scanner = self._scanner(name=f"ops-{_label}")
        self._observation(scanner, {"verdict": "yes"})
        self._observation(scanner, {"verdict": "no"}, session_id="s2")
        action = self._alert(scanner, {"metric": "count", "operator": op, "threshold": threshold})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, expected)
        if expected == AlertStatus.NOT_BREACHED:
            run.refresh_from_db()
            self.assertEqual(run.synthesized_markdown, "")

    def test_selection_predicate_gates_what_counts(self) -> None:
        # "Alert me whenever a user gets tag X": the shared targeting predicate is the match; a
        # dropped predicate would make every alert fire on all observations.
        scanner = self._scanner(scanner_type=ScannerType.CLASSIFIER, name="tagger")
        self._observation(scanner, {"tags": ["rage-click"]})
        self._observation(scanner, {"tags": ["happy-path"]}, session_id="s2")
        action = self._alert(
            scanner,
            {"metric": "count", "operator": "gte", "threshold": 1},
            selection={"tags": ["rage-click"]},
        )

        result, _ = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        self.assertEqual(result.observation_count, 1)

        # The same window with a non-matching tag filter must not fire.
        other = self._alert(
            self._scanner(scanner_type=ScannerType.CLASSIFIER, name="tagger2"),
            {"metric": "count", "operator": "gte", "threshold": 1},
            selection={"tags": ["missing"]},
        )
        result, _ = self._evaluate(other, key="k2")
        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)

    def test_avg_score_metric(self) -> None:
        scanner = self._scanner(scanner_type=ScannerType.SCORER, name="scorer")
        self._observation(scanner, {"score": 2})
        self._observation(scanner, {"score": 4}, session_id="s2")
        action = self._alert(scanner, {"metric": "avg_score", "operator": "lte", "threshold": 3})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        self.assertEqual(result.metric_value, 3.0)
        run.refresh_from_db()
        self.assertIn("average score over the last 24 hours was 3", run.synthesized_markdown)

    def test_avg_over_empty_window_never_fires(self) -> None:
        # An unmeasurable metric must not breach — including operators like `lt` that a "0" would satisfy.
        scanner = self._scanner(scanner_type=ScannerType.SCORER, name="quiet-scorer")
        action = self._alert(scanner, {"metric": "avg_score", "operator": "lt", "threshold": 5})

        result, _ = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)
        self.assertIsNone(result.metric_value)

    def test_retry_after_persist_reports_fired_without_reevaluating(self) -> None:
        scanner = self._scanner(name="idem")
        self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "operator": "gte", "threshold": 1})

        first, run = self._evaluate(action)
        self.assertEqual(first.status, AlertStatus.FIRED)

        # New observations arriving between attempts must not change the already-persisted outcome.
        self._observation(scanner, {"verdict": "yes"}, session_id="s9")
        second = _evaluate(EvaluateAlertInputs(run_id=run.id, team_id=self.team.id))
        self.assertEqual(second.status, AlertStatus.FIRED)
        self.assertEqual(second.observation_count, 1)

    def test_rolling_window_excludes_older_observations(self) -> None:
        # window_days=1 must not count what a longer window would; window_days=7 must.
        scanner = self._scanner(name="windowed")
        self._observation(scanner, {"verdict": "yes"}, age_days=3)
        short = self._alert(scanner, {"metric": "count", "operator": "gte", "threshold": 1, "window_days": 1})
        result, _ = self._evaluate(short)
        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)

        wide = self._alert(
            self._scanner(name="windowed2"),
            {"metric": "count", "operator": "gte", "threshold": 1, "window_days": 7},
        )
        self._observation(wide.scanner, {"verdict": "yes"}, session_id="s7", age_days=3)
        result, _ = self._evaluate(wide, key="k7")
        self.assertEqual(result.status, AlertStatus.FIRED)

    def test_breach_fires_once_until_it_clears(self) -> None:
        # A rolling window stays breached across checks; only the transition into breach notifies.
        scanner = self._scanner(name="steady")
        self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "operator": "gte", "threshold": 1, "window_days": 7})

        first, first_run = self._evaluate(action)
        self.assertEqual(first.status, AlertStatus.FIRED)
        VisionActionRun.objects.for_team(self.team.id).filter(pk=first_run.pk).update(
            status=VisionActionRunStatus.COMPLETED
        )

        second, _ = self._evaluate(action, key="k2")
        self.assertEqual(second.status, AlertStatus.STILL_BREACHED)

        # After a not-breached check (the condition cleared), a new breach notifies again.
        third, third_run = self._evaluate(action, key="k3")
        VisionActionRun.objects.for_team(self.team.id).filter(pk=third_run.pk).update(
            status=VisionActionRunStatus.SKIPPED
        )
        fourth, _ = self._evaluate(action, key="k4")
        self.assertEqual(fourth.status, AlertStatus.FIRED)

    def test_every_match_fires_per_new_match_and_only_new(self) -> None:
        # "Every time the result is YES, Slack me": each check reports only what's new since the
        # previous check — no still-breached suppression, and no re-reporting of old matches.
        scanner = self._scanner(name="everytime")
        action = self._alert(scanner, {"frequency": "every_match"}, selection={"verdict": ["yes"]})

        self._observation(scanner, {"verdict": "yes"})
        first, first_run = self._evaluate(action)
        self.assertEqual(first.status, AlertStatus.FIRED)
        self.assertEqual(first.observation_count, 1)
        first_run.refresh_from_db()
        self.assertIn("1 new matching observation since the last check", first_run.synthesized_markdown)

        # A second match after the first check fires again (the on_breach flavor would suppress this).
        self._observation(scanner, {"verdict": "yes"}, session_id="s2")
        second, _ = self._evaluate(action, key="k2")
        self.assertEqual(second.status, AlertStatus.FIRED)
        self.assertEqual(second.observation_count, 1)

        # Nothing new since the last check → quiet.
        third, _ = self._evaluate(action, key="k3")
        self.assertEqual(third.status, AlertStatus.NOT_BREACHED)

    def test_every_match_ignores_observations_from_before_the_alert_existed(self) -> None:
        scanner = self._scanner(name="no-history")
        self._observation(scanner, {"verdict": "yes"}, age_days=0.5)
        action = self._alert(scanner, {"frequency": "every_match"}, selection={"verdict": ["yes"]})
        VisionAction.all_teams.filter(pk=action.pk).update(created_at=timezone.now())

        result, _ = self._evaluate(action)
        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)

    def test_malformed_config_never_fires(self) -> None:
        scanner = self._scanner(name="broken")
        self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "operator": "gte", "threshold": "high"})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")
