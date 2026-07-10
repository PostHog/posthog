from datetime import timedelta

from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import (
    ReplayScannerPromptSuggestion,
    SuggestionStatus,
)
from products.replay_vision.backend.prompt_evaluation import (
    EVALUATION_SESSION_CAP,
    classify_outcome,
    primary_outcome,
    select_evaluation_observations,
    summarize_results,
)
from products.replay_vision.backend.quota import MONTHLY_OBSERVATION_QUOTA, compute_quota_snapshot
from products.replay_vision.backend.temporal.activities.evaluate_prompt_suggestion import (
    finalize_evaluation_activity,
    record_evaluation_result_activity,
    select_evaluation_sessions_activity,
)
from products.replay_vision.backend.temporal.evaluation_types import (
    EvaluationSession,
    FinalizeEvaluationInputs,
    RecordEvaluationResultInputs,
    SelectEvaluationSessionsInputs,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


class TestPromptEvaluation(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

    def _create_rated(
        self, session_id: str, is_correct: bool, verdict: str = "no", days_ago: int = 0
    ) -> ReplayObservation:
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=session_id,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_result={
                "model_output": {"verdict": verdict, "confidence": 0.9, "scanner_type": "monitor"},
                "signals_count": 0,
            },
        )
        if days_ago:
            ReplayObservation.objects.filter(id=observation.id).update(
                created_at=timezone.now() - timedelta(days=days_ago)
            )
        ReplayObservationLabel.objects.create(observation=observation, is_correct=is_correct)
        return observation

    def _create_suggestion(self, **overrides) -> ReplayScannerPromptSuggestion:
        defaults = {
            "scanner": self.scanner,
            "team": self.team,
            "suggested_prompt": "Did the user place an order? Only answer yes on a confirmation page.",
            "base_prompt": "did the user check out?",
            "status": SuggestionStatus.PENDING,
            "scanner_version": 1,
        }
        defaults.update(overrides)
        return ReplayScannerPromptSuggestion.objects.create(**defaults)

    @parameterized.expand(
        [
            ({"verdict": "Yes "}, "Verdict: yes"),
            ({"verdict": "no", "tags": ["a"]}, "Verdict: no"),
            ({"tags": ["Churn ", "bug", "churn"]}, "Tags: bug, churn, churn"),
            ({"score": 7}, None),
            ({}, None),
            (None, None),
        ]
    )
    def test_primary_outcome_normalizes_discrete_outputs(self, output, expected) -> None:
        self.assertEqual(primary_outcome(output), expected)

    @parameterized.expand(
        [
            (True, "Verdict: yes", "Verdict: yes", "kept"),
            (True, "Verdict: yes", "Verdict: no", "regressed"),
            (False, "Verdict: yes", "Verdict: no", "fixed"),
            (False, "Verdict: yes", "Verdict: yes", "still_wrong"),
            # An empty outcome (e.g. a classifier with no tags) is valid, not an error.
            (True, None, None, "kept"),
            (False, "Tags: bug", None, "fixed"),
        ]
    )
    def test_classify_outcome(self, rated_correct, before, after, expected) -> None:
        self.assertEqual(classify_outcome(rated_correct, before, after), expected)

    def test_selection_prioritizes_thumbs_down_then_newest_within_cap(self) -> None:
        for i in range(EVALUATION_SESSION_CAP):
            self._create_rated(f"up-{i}", True, days_ago=i + 1)
        newest_down = self._create_rated("down-new", False, days_ago=0)
        oldest_down = self._create_rated("down-old", False, days_ago=30)

        selected = select_evaluation_observations(self.scanner)

        self.assertEqual(len(selected), EVALUATION_SESSION_CAP)
        self.assertEqual([o.session_id for o in selected[:2]], [newest_down.session_id, oldest_down.session_id])
        self.assertTrue(all(o.session_id.startswith("up-") for o in selected[2:]))

        # A session_limit lowers the cap and keeps the thumbs-down priority. It can never raise the cap.
        limited = select_evaluation_observations(self.scanner, session_limit=1)
        self.assertEqual([o.session_id for o in limited], [newest_down.session_id])
        self.assertEqual(
            len(select_evaluation_observations(self.scanner, session_limit=EVALUATION_SESSION_CAP + 5)),
            EVALUATION_SESSION_CAP,
        )

    def test_select_activity_builds_suggested_prompt_snapshot_and_marks_running(self) -> None:
        self._create_rated("sess-1", False)
        # The scanner moved on since the rated observation: the snapshot must reflect current config.
        self.scanner.scanner_config = {"prompt": "current prompt", "extra_setting": True}
        self.scanner.emits_signals = True
        self.scanner.save()
        suggestion = self._create_suggestion()

        output = select_evaluation_sessions_activity(
            SelectEvaluationSessionsInputs(suggestion_id=suggestion.id, team_id=self.team.id)
        )

        assert output.snapshot is not None
        self.assertEqual(output.snapshot.scanner_config["prompt"], suggestion.suggested_prompt)
        self.assertTrue(output.snapshot.scanner_config["extra_setting"])
        self.assertFalse(output.snapshot.emits_signals)
        self.assertEqual([s.session_id for s in output.sessions], ["sess-1"])
        self.assertEqual(output.sessions[0].before_outcome, "Verdict: no")
        suggestion.refresh_from_db()
        assert suggestion.evaluation is not None
        self.assertEqual(suggestion.evaluation["status"], "running")
        self.assertEqual(suggestion.evaluation["total"], 1)
        self.assertNotEqual(suggestion.evaluation["labels_fingerprint"], "")

    def test_record_and_finalize_produce_summary_and_dedup_retries(self) -> None:
        observation = self._create_rated("sess-1", False, verdict="yes")
        suggestion = self._create_suggestion(evaluation={"status": "running", "results": []})
        session = EvaluationSession(
            observation_id=observation.id,
            session_id="sess-1",
            rated_correct=False,
            before_outcome="Verdict: yes",
        )
        inputs = RecordEvaluationResultInputs(
            suggestion_id=suggestion.id,
            team_id=self.team.id,
            session=session,
            after_output={"verdict": "no"},
        )
        record_evaluation_result_activity(inputs)
        record_evaluation_result_activity(inputs)  # an activity retry must not double-count

        finalize_evaluation_activity(FinalizeEvaluationInputs(suggestion_id=suggestion.id, team_id=self.team.id))

        suggestion.refresh_from_db()
        assert suggestion.evaluation is not None
        self.assertEqual(len(suggestion.evaluation["results"]), 1)
        self.assertEqual(suggestion.evaluation["results"][0]["outcome"], "fixed")
        self.assertEqual(suggestion.evaluation["status"], "succeeded")
        self.assertEqual(
            suggestion.evaluation["summary"], {"kept": 0, "regressed": 0, "fixed": 1, "still_wrong": 0, "errors": 0}
        )
        self.assertIsNotNone(suggestion.evaluation["finished_at"])
        # The retried run charged the org's quota exactly once, inside the current monthly window.
        receipts = ReplayObservationUsage.objects.filter(organization_id=self.team.organization_id)
        self.assertEqual(receipts.count(), 1)
        self.assertEqual(compute_quota_snapshot(self.team.organization_id).usage_this_month, 1)

    def test_failed_session_run_does_not_charge_quota(self) -> None:
        observation = self._create_rated("sess-1", False)
        suggestion = self._create_suggestion(evaluation={"status": "running", "results": []})

        record_evaluation_result_activity(
            RecordEvaluationResultInputs(
                suggestion_id=suggestion.id,
                team_id=self.team.id,
                session=EvaluationSession(
                    observation_id=observation.id,
                    session_id="sess-1",
                    rated_correct=False,
                    before_outcome="Verdict: no",
                ),
                error="rasterize failed",
            )
        )

        suggestion.refresh_from_db()
        assert suggestion.evaluation is not None
        self.assertEqual(suggestion.evaluation["results"][0]["outcome"], "error")
        self.assertEqual(ReplayObservationUsage.objects.count(), 0)

    def test_empty_after_output_is_a_valid_outcome_and_charges(self) -> None:
        observation = self._create_rated("sess-1", False)
        suggestion = self._create_suggestion(evaluation={"status": "running", "results": []})

        record_evaluation_result_activity(
            RecordEvaluationResultInputs(
                suggestion_id=suggestion.id,
                team_id=self.team.id,
                session=EvaluationSession(
                    observation_id=observation.id,
                    session_id="sess-1",
                    rated_correct=False,
                    before_outcome="Tags: bug",
                ),
                after_output={"tags": []},
            )
        )

        suggestion.refresh_from_db()
        assert suggestion.evaluation is not None
        result = suggestion.evaluation["results"][0]
        self.assertEqual(result["outcome"], "fixed")
        self.assertIsNone(result["after"])
        self.assertIsNone(result["error"])
        self.assertEqual(ReplayObservationUsage.objects.count(), 1)

    def test_retest_charges_quota_again(self) -> None:
        observation = self._create_rated("sess-1", False)
        suggestion = self._create_suggestion(
            evaluation={"status": "running", "results": [], "started_at": "2026-07-01T00:00:00+00:00"}
        )
        inputs = RecordEvaluationResultInputs(
            suggestion_id=suggestion.id,
            team_id=self.team.id,
            session=EvaluationSession(
                observation_id=observation.id,
                session_id="sess-1",
                rated_correct=False,
                before_outcome="Verdict: no",
            ),
            after_output={"verdict": "yes"},
        )
        record_evaluation_result_activity(inputs)

        # A fresh test run stamps a new started_at, so the same session must charge again.
        suggestion.refresh_from_db()
        suggestion.evaluation = {"status": "running", "results": [], "started_at": "2026-07-02T00:00:00+00:00"}
        suggestion.save(update_fields=["evaluation"])
        record_evaluation_result_activity(inputs)

        self.assertEqual(ReplayObservationUsage.objects.count(), 2)

    def test_summarize_counts_errors(self) -> None:
        results = [{"outcome": "kept"}, {"outcome": "error"}, {"outcome": "fixed"}, {"outcome": "fixed"}]
        self.assertEqual(
            summarize_results(results), {"kept": 1, "regressed": 0, "fixed": 2, "still_wrong": 0, "errors": 1}
        )


class TestPromptEvaluationApi(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

    def _url(self, suggestion_id) -> str:
        return (
            f"/api/projects/{self.team.id}/vision/scanners/{self.scanner.id}/"
            f"prompt_suggestions/{suggestion_id}/evaluate/"
        )

    def _create_pending_suggestion(self, **overrides) -> ReplayScannerPromptSuggestion:
        defaults = {
            "scanner": self.scanner,
            "team": self.team,
            "suggested_prompt": "new prompt",
            "status": SuggestionStatus.PENDING,
            "scanner_version": 1,
        }
        defaults.update(overrides)
        return ReplayScannerPromptSuggestion.objects.create(**defaults)

    def _create_rated(self, session_id: str = "sess-1") -> None:
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=session_id,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_result={"model_output": {"verdict": "no"}, "signals_count": 0},
        )
        ReplayObservationLabel.objects.create(observation=observation, is_correct=False)

    def _mock_temporal(self):
        client = MagicMock()
        client.start_workflow = AsyncMock()
        return patch("products.replay_vision.backend.api.prompt_suggestions.sync_connect", return_value=client), client

    def test_evaluate_starts_workflow_and_stamps_running(self) -> None:
        self._create_rated()
        suggestion = self._create_pending_suggestion()
        connect_patch, client = self._mock_temporal()
        with connect_patch:
            resp = self.client.post(self._url(suggestion.id))

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["evaluation"]["status"], "running")
        # The stub reserves the planned spend so the quota snapshot counts it immediately.
        self.assertEqual(resp.json()["evaluation"]["total"], 1)
        client.start_workflow.assert_awaited_once()
        self.assertIn(str(suggestion.id), client.start_workflow.await_args.kwargs["id"])
        # Without an explicit session_limit the test runs up to the cap.
        self.assertEqual(client.start_workflow.await_args.args[1].session_limit, EVALUATION_SESSION_CAP)

    def test_evaluate_while_running_does_not_restart(self) -> None:
        self._create_rated()
        suggestion = self._create_pending_suggestion(
            evaluation={"status": "running", "started_at": timezone.now().isoformat(), "results": [], "total": 3}
        )
        connect_patch, client = self._mock_temporal()
        with connect_patch:
            resp = self.client.post(self._url(suggestion.id))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["evaluation"]["total"], 3)
        client.start_workflow.assert_not_awaited()

    def test_stale_running_evaluation_reports_failed_and_can_be_restarted(self) -> None:
        # A workflow killed without finalizing must not leave the suggestion stuck "running" forever.
        self._create_rated()
        suggestion = self._create_pending_suggestion(
            evaluation={
                "status": "running",
                "started_at": (timezone.now() - timedelta(hours=2)).isoformat(),
                "results": [],
                "total": 3,
                "summary": None,
            }
        )

        current = self.client.get(
            f"/api/projects/{self.team.id}/vision/scanners/{self.scanner.id}/prompt_suggestions/current/"
        )
        self.assertEqual(current.json()["suggestion"]["evaluation"]["status"], "failed")

        connect_patch, client = self._mock_temporal()
        with connect_patch:
            resp = self.client.post(self._url(suggestion.id))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["evaluation"]["status"], "running")
        client.start_workflow.assert_awaited_once()

    def test_failed_workflow_start_rolls_back_running_state(self) -> None:
        # If Temporal is down, a "running" row with no workflow behind it would block re-testing.
        self._create_rated()
        suggestion = self._create_pending_suggestion()
        connect_patch, client = self._mock_temporal()
        client.start_workflow.side_effect = RuntimeError("temporal unavailable")
        with connect_patch:
            resp = self.client.post(self._url(suggestion.id))

        self.assertEqual(resp.status_code, 500)
        suggestion.refresh_from_db()
        self.assertIsNone(suggestion.evaluation)

    def test_evaluate_refuses_when_quota_exhausted(self) -> None:
        self._create_rated()
        suggestion = self._create_pending_suggestion()
        quota = MagicMock(remaining=0, monthly_quota=100, period_end=timezone.now())
        connect_patch, client = self._mock_temporal()
        with (
            connect_patch,
            patch("products.replay_vision.backend.api.prompt_suggestions.compute_quota_snapshot", return_value=quota),
        ):
            resp = self.client.post(self._url(suggestion.id))

        self.assertEqual(resp.status_code, 402)
        client.start_workflow.assert_not_awaited()
        suggestion.refresh_from_db()
        self.assertIsNone(suggestion.evaluation)

    def test_evaluate_refuses_when_planned_sessions_exceed_remaining_quota(self) -> None:
        for i in range(3):
            self._create_rated(f"sess-{i}")
        suggestion = self._create_pending_suggestion()
        quota = MagicMock(remaining=2, monthly_quota=100, period_end=timezone.now())
        connect_patch, client = self._mock_temporal()
        with (
            connect_patch,
            patch("products.replay_vision.backend.api.prompt_suggestions.compute_quota_snapshot", return_value=quota),
        ):
            # The default limit plans 3 re-runs but only 2 observations remain this month.
            resp = self.client.post(self._url(suggestion.id))
            self.assertEqual(resp.status_code, 402)
            client.start_workflow.assert_not_awaited()

            # Lowering the session count to what is left starts the test with that limit.
            resp = self.client.post(self._url(suggestion.id), {"session_limit": 2}, format="json")
            self.assertEqual(resp.status_code, 200, resp.json())
            self.assertEqual(client.start_workflow.await_args.args[1].session_limit, 2)

    def test_running_evaluation_elsewhere_counts_against_quota(self) -> None:
        # Without in-flight accounting, starting tests on several suggestions could overcommit the month.
        self._create_rated()
        suggestion = self._create_pending_suggestion()
        other_scanner = self._create_scanner(name="other")
        ReplayScannerPromptSuggestion.objects.create(
            scanner=other_scanner,
            team=self.team,
            suggested_prompt="p",
            status=SuggestionStatus.PENDING,
            scanner_version=1,
            evaluation={
                "status": "running",
                "started_at": timezone.now().isoformat(),
                "results": [],
                "total": MONTHLY_OBSERVATION_QUOTA,
            },
        )
        connect_patch, client = self._mock_temporal()
        with connect_patch:
            resp = self.client.post(self._url(suggestion.id))

        self.assertEqual(resp.status_code, 402)
        client.start_workflow.assert_not_awaited()

    @parameterized.expand([("zero", 0), ("above_cap", EVALUATION_SESSION_CAP + 1)])
    def test_evaluate_rejects_out_of_range_session_limit(self, _name: str, limit: int) -> None:
        self._create_rated()
        suggestion = self._create_pending_suggestion()
        connect_patch, client = self._mock_temporal()
        with connect_patch:
            resp = self.client.post(self._url(suggestion.id), {"session_limit": limit}, format="json")

        self.assertEqual(resp.status_code, 400)
        client.start_workflow.assert_not_awaited()

    @parameterized.expand(
        [
            ("not_pending", {"status": SuggestionStatus.DISMISSED}, ScannerType.MONITOR, True),
            ("unsupported_type", {}, ScannerType.SUMMARIZER, True),
            ("no_ratings", {}, ScannerType.MONITOR, False),
        ]
    )
    def test_evaluate_gates(self, _name, suggestion_overrides, scanner_type, with_rating) -> None:
        self.scanner.scanner_type = scanner_type
        self.scanner.save()
        if with_rating:
            self._create_rated()
        suggestion = self._create_pending_suggestion(**suggestion_overrides)
        connect_patch, client = self._mock_temporal()
        with connect_patch:
            resp = self.client.post(self._url(suggestion.id))

        self.assertEqual(resp.status_code, 400)
        client.start_workflow.assert_not_awaited()
        suggestion.refresh_from_db()
        self.assertIsNone(suggestion.evaluation)
