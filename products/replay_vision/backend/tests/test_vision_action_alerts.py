from datetime import timedelta

from posthog.test.base import BaseTest

from django.conf import settings
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
            # Windows bound on completed_at; backdate created_at too so display ordering matches.
            aged = timezone.now() - timedelta(days=age_days)
            ReplayObservation.objects.filter(pk=obs.pk).update(created_at=aged, completed_at=aged)
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

    def _record(self, run: VisionActionRun, status: str, error: dict | None = None) -> None:
        # Mirror the workflow's final run update so state resolution sees what production would.
        VisionActionRun.objects.for_team(self.team.id).filter(pk=run.pk).update(status=status, error=error)

    def test_count_alert_fires_and_persists_deterministic_message(self) -> None:
        scanner = self._scanner()
        older = self._observation(scanner, {"verdict": "yes", "reasoning": "user hit the bug"}, age_days=0.01)
        newest = self._observation(scanner, {"verdict": "yes", "reasoning": "again"}, session_id="s2")
        action = self._alert(scanner, {"metric": "count", "threshold": 2})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        self.assertEqual(result.observation_count, 2)
        self.assertEqual(result.metric_value, 2.0)
        run.refresh_from_db()
        run_url = f"{settings.SITE_URL}/project/{self.team.id}/replay-vision/actions/{action.id}/runs/{run.pk}"
        self.assertIn(f"Alert: [alert-watcher]({run_url})** for scanner watcher", run.synthesized_markdown)
        self.assertIn("over the last 24 hours", run.synthesized_markdown)
        self.assertIn("at or above the threshold of 2", run.synthesized_markdown)
        self.assertIn("2 observations matched", run.synthesized_markdown)
        # Example lines cite observations by their position in observation_ids (newest first), so the
        # in-app view and the Slack pass both resolve each citation to the right observation.
        self.assertEqual(run.observation_ids, [str(newest.id), str(older.id)])
        self.assertIn("[obs 1]", run.synthesized_markdown)
        self.assertIn("[obs 2]", run.synthesized_markdown)
        self.assertIn(f"<{run_url}|alert-watcher>", run.output["slack"])
        self.assertIn(f"/observations/{newest.id}|[1]>", run.output["slack"])
        self.assertIn(f"/observations/{older.id}|[2]>", run.output["slack"])
        # Every match is already listed, so there's no "see all" overflow link to add noise.
        self.assertNotIn("See all", run.synthesized_markdown)

    def test_many_matches_list_only_examples_and_link_to_the_run(self) -> None:
        scanner = self._scanner()
        for i in range(7):
            self._observation(scanner, {"verdict": "yes"}, session_id=f"s{i}")
        action = self._alert(scanner, {"metric": "count", "threshold": 7})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown.count("- ("), 5)
        run_url = f"{settings.SITE_URL}/project/{self.team.id}/replay-vision/actions/{action.id}/runs/{run.pk}"
        self.assertIn(f"[See all 7 matches]({run_url})", run.synthesized_markdown)
        self.assertIn(f"<{run_url}|See all 7 matches>", run.output["slack"])

    @parameterized.expand(
        [
            # direction defaults to above: fires when the metric is at or above the threshold.
            ("above_under_threshold", {"threshold": 3}, AlertStatus.NOT_BREACHED),
            ("above_at_threshold", {"threshold": 2}, AlertStatus.FIRED),
            # below inverts the comparison (inclusive): fires when the metric is at or below it.
            ("below_at_threshold", {"threshold": 2, "direction": "below"}, AlertStatus.FIRED),
            ("below_over_threshold", {"threshold": 1, "direction": "below"}, AlertStatus.NOT_BREACHED),
        ]
    )
    def test_threshold_semantics_over_count(self, _label: str, config: dict, expected: AlertStatus) -> None:
        scanner = self._scanner(name=f"ops-{_label}")
        self._observation(scanner, {"verdict": "yes"})
        self._observation(scanner, {"verdict": "no"}, session_id="s2")
        action = self._alert(scanner, {"metric": "count", **config})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, expected)
        if expected == AlertStatus.NOT_BREACHED:
            run.refresh_from_db()
            self.assertEqual(run.synthesized_markdown, "")

    def test_recovery_bookends_the_breach_and_rearms_the_alert(self) -> None:
        # fire → recover → fire again. The recovery run must be persisted as a visible message AND
        # must read as "cleared" in state resolution — misread as a breach, it would suppress the
        # next firing forever (a fired run also has a persisted message).
        scanner = self._scanner()
        obs = self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "threshold": 1})

        fired, fired_run = self._evaluate(action)
        self.assertEqual(fired.status, AlertStatus.FIRED)
        self._record(fired_run, VisionActionRunStatus.COMPLETED)

        # The observation ages out of the rolling window: count drops to a measurable 0.
        aged = timezone.now() - timedelta(days=2)
        ReplayObservation.objects.filter(pk=obs.pk).update(completed_at=aged, created_at=aged)
        recovered, recovery_run = self._evaluate(action, key="k2")

        self.assertEqual(recovered.status, AlertStatus.RECOVERED)
        recovery_run.refresh_from_db()
        self.assertIn("Recovered: [alert-watcher](", recovery_run.synthesized_markdown)
        self.assertIn("below the threshold of 1", recovery_run.synthesized_markdown)
        self.assertIn("had been firing since", recovery_run.synthesized_markdown)
        self.assertTrue(recovery_run.output["recovered"])
        self._record(recovery_run, VisionActionRunStatus.COMPLETED)

        # A fresh match after recovery is a new incident — it must fire, not report still_breached.
        self._observation(scanner, {"verdict": "yes"}, session_id="s-new")
        refired, _ = self._evaluate(action, key="k3")
        self.assertEqual(refired.status, AlertStatus.FIRED)

    def test_unmeasurable_window_after_breach_rearms_without_recovery_row(self) -> None:
        # An avg over an empty window has no measurement, so it can't claim "back at X" — the alert
        # re-arms via a quiet not_breached skip instead of a recovery bookend.
        scanner = self._scanner(scanner_type=ScannerType.SCORER, name="fading-scorer")
        obs = self._observation(scanner, {"score": 5})
        action = self._alert(scanner, {"metric": "avg_score", "threshold": 4})

        fired, fired_run = self._evaluate(action)
        self.assertEqual(fired.status, AlertStatus.FIRED)
        self._record(fired_run, VisionActionRunStatus.COMPLETED)

        aged = timezone.now() - timedelta(days=2)
        ReplayObservation.objects.filter(pk=obs.pk).update(completed_at=aged, created_at=aged)
        result, run = self._evaluate(action, key="k2")

        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")

    def test_below_direction_message_says_at_or_below(self) -> None:
        scanner = self._scanner(scanner_type=ScannerType.SCORER, name="floor-scorer")
        self._observation(scanner, {"score": 2})
        action = self._alert(scanner, {"metric": "avg_score", "threshold": 3, "direction": "below"})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        run.refresh_from_db()
        self.assertIn("at or below the threshold of 3", run.synthesized_markdown)

    def test_slack_output_escapes_mrkdwn_control_sequences(self) -> None:
        # Freeform tags are observation-derived untrusted text that the alert message interpolates
        # verbatim; Slack treats <...> as control sequences, so an unescaped `<!channel>` tag would
        # ping the whole channel from inside a report.
        scanner = self._scanner(scanner_type=ScannerType.CLASSIFIER, name="tagger-evil")
        action = self._alert(scanner, {"frequency": "every_match", "metric": "count"})
        self._observation(scanner, {"tags": [], "tags_freeform": ["<!channel> pwned"]})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        run.refresh_from_db()
        self.assertIn("&lt;!channel&gt;", run.output["slack"])
        self.assertNotIn("<!channel>", run.output["slack"])

    def test_selection_predicate_gates_what_counts(self) -> None:
        # "Alert me whenever a user gets tag X": the shared targeting predicate is the match; a
        # dropped predicate would make every alert fire on all observations.
        scanner = self._scanner(scanner_type=ScannerType.CLASSIFIER, name="tagger")
        self._observation(scanner, {"tags": ["rage-click"]})
        self._observation(scanner, {"tags": ["happy-path"]}, session_id="s2")
        action = self._alert(
            scanner,
            {"metric": "count", "threshold": 1},
            selection={"tags": ["rage-click"]},
        )

        result, _ = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        self.assertEqual(result.observation_count, 1)

        # The same window with a non-matching tag filter must not fire.
        other = self._alert(
            self._scanner(scanner_type=ScannerType.CLASSIFIER, name="tagger2"),
            {"metric": "count", "threshold": 1},
            selection={"tags": ["missing"]},
        )
        result, _ = self._evaluate(other, key="k2")
        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)

    def test_avg_score_metric(self) -> None:
        scanner = self._scanner(scanner_type=ScannerType.SCORER, name="scorer")
        self._observation(scanner, {"score": 2})
        self._observation(scanner, {"score": 4}, session_id="s2")
        action = self._alert(scanner, {"metric": "avg_score", "threshold": 3})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.FIRED)
        self.assertEqual(result.metric_value, 3.0)
        run.refresh_from_db()
        self.assertIn("average score over the last 24 hours was 3", run.synthesized_markdown)

    @parameterized.expand([("above", "above"), ("below", "below")])
    def test_avg_over_empty_window_never_fires(self, _label: str, direction: str) -> None:
        # An unmeasurable metric must not breach in either direction — a None average must not be
        # coerced to a comparable 0 (below would otherwise fire on every quiet window).
        scanner = self._scanner(scanner_type=ScannerType.SCORER, name=f"quiet-scorer-{_label}")
        threshold = 0 if direction == "above" else 100
        action = self._alert(scanner, {"metric": "avg_score", "threshold": threshold, "direction": direction})

        result, _ = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)
        self.assertIsNone(result.metric_value)

    def test_retry_after_persist_reports_fired_without_reevaluating(self) -> None:
        scanner = self._scanner(name="idem")
        self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "threshold": 1})

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
        short = self._alert(scanner, {"metric": "count", "threshold": 1, "window_days": 1})
        result, _ = self._evaluate(short)
        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)

        wide = self._alert(
            self._scanner(name="windowed2"),
            {"metric": "count", "threshold": 1, "window_days": 7},
        )
        self._observation(wide.scanner, {"verdict": "yes"}, session_id="s7", age_days=3)
        result, _ = self._evaluate(wide, key="k7")
        self.assertEqual(result.status, AlertStatus.FIRED)

    def test_breach_fires_once_until_it_clears(self) -> None:
        # A rolling window stays breached across checks; only the transition into breach notifies.
        # Each check's outcome is recorded the way the workflow records it.
        scanner = self._scanner(name="steady")
        self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "threshold": 1, "window_days": 7})

        first, first_run = self._evaluate(action)
        self.assertEqual(first.status, AlertStatus.FIRED)
        self._record(first_run, VisionActionRunStatus.COMPLETED)

        second, second_run = self._evaluate(action, key="k2")
        self.assertEqual(second.status, AlertStatus.STILL_BREACHED)
        self._record(second_run, VisionActionRunStatus.SKIPPED, {"skip_reason": "still_breached"})

        # Once a check observes the condition clear (window emptied), the next breach notifies again.
        cleared_run = VisionActionRun(vision_action=action, team=self.team, idempotency_key="k3")
        cleared_run.save()
        self._record(cleared_run, VisionActionRunStatus.SKIPPED, {"skip_reason": "not_breached"})

        fourth, _ = self._evaluate(action, key="k4")
        self.assertEqual(fourth.status, AlertStatus.FIRED)

    def test_transient_failure_does_not_rearm_a_breached_alert(self) -> None:
        # A crashed check between two breached checks must not cause a duplicate notification: the
        # state comes from the last check that meaningfully evaluated, walking past FAILED runs.
        scanner = self._scanner(name="flaky-check")
        self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "threshold": 1, "window_days": 7})

        first, first_run = self._evaluate(action)
        self.assertEqual(first.status, AlertStatus.FIRED)
        self._record(first_run, VisionActionRunStatus.COMPLETED)

        failed_run = VisionActionRun(vision_action=action, team=self.team, idempotency_key="k-fail")
        failed_run.save()
        self._record(failed_run, VisionActionRunStatus.FAILED, {"message": "boom"})

        third, _ = self._evaluate(action, key="k3")
        self.assertEqual(third.status, AlertStatus.STILL_BREACHED)

    def test_every_match_failed_check_does_not_lose_its_window(self) -> None:
        # A crashed every-match check must not advance the coverage cursor: its window's matches are
        # picked up by the next successful check instead of being silently dropped.
        scanner = self._scanner(name="lossless")
        action = self._alert(scanner, {"frequency": "every_match"}, selection={"verdict": ["yes"]})

        self._observation(scanner, {"verdict": "yes"})
        first, first_run = self._evaluate(action)
        self.assertEqual(first.status, AlertStatus.FIRED)
        self._record(first_run, VisionActionRunStatus.COMPLETED)

        self._observation(scanner, {"verdict": "yes"}, session_id="s2")
        failed_run = VisionActionRun(vision_action=action, team=self.team, idempotency_key="k-fail")
        failed_run.save()
        self._record(failed_run, VisionActionRunStatus.FAILED, {"message": "boom"})

        third, _ = self._evaluate(action, key="k3")
        self.assertEqual(third.status, AlertStatus.FIRED)
        self.assertEqual(third.observation_count, 1)

    def test_malformed_config_never_fires(self) -> None:
        scanner = self._scanner(name="broken")
        self._observation(scanner, {"verdict": "yes"})
        action = self._alert(scanner, {"metric": "count", "threshold": "high"})

        result, run = self._evaluate(action)

        self.assertEqual(result.status, AlertStatus.NOT_BREACHED)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")
