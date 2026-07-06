from datetime import timedelta
from typing import Any

from unittest.mock import patch

from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import (
    ReplayScannerPromptSuggestion,
    SuggestionStatus,
)
from products.replay_vision.backend.prompt_suggestions import _LlmPromptSuggestion, refresh_prompt_suggestion_if_stale
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


class TestPromptSuggestions(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.canned = _LlmPromptSuggestion(
            suggested_prompt="Did the user place an order? Only answer yes on an order confirmation.",
            rationale="Tightened the yes condition using the rated sessions.",
        )
        # The agentic loop has its own tests. API tests mock it out, along with its single-shot fallback.
        self.agentic_patcher = patch(
            "products.replay_vision.backend.prompt_suggestions._generate_agentic", side_effect=self._agentic
        )
        self.mock_agentic = self.agentic_patcher.start()
        self.generate_patcher = patch(
            "products.replay_vision.backend.prompt_suggestions._generate", side_effect=self._single_shot
        )
        self.mock_generate = self.generate_patcher.start()

    def _agentic(self, **_kwargs) -> _LlmPromptSuggestion:
        return self.canned

    def _single_shot(self, **_kwargs) -> _LlmPromptSuggestion:
        return self.canned

    def tearDown(self) -> None:
        self.generate_patcher.stop()
        self.agentic_patcher.stop()
        super().tearDown()

    def _suggestions_url(self, suffix: str = "") -> str:
        return f"{self.scanners_url}{self.scanner.id}/prompt_suggestions/{suffix}"

    def _create_rated_observation(self, session_id: str, is_correct: bool, feedback: str = "") -> ReplayObservation:
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=session_id,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_result={
                "model_output": {"verdict": "no", "confidence": 0.9, "scanner_type": "monitor"},
                "signals_count": 0,
            },
        )
        ReplayObservationLabel.objects.create(observation=observation, is_correct=is_correct, feedback=feedback)
        return observation

    def test_generate_persists_suggestion_and_supersedes_previous_pending(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        self._create_rated_observation("sess-2", True)

        first = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(first.status_code, 200, first.json())
        self.assertEqual(first.json()["based_on_up"], 1)
        self.assertEqual(first.json()["based_on_down"], 1)
        self.assertEqual(first.json()["status"], "pending")
        # The prompt it was generated against is stored so the UI can diff against it.
        self.assertEqual(first.json()["base_prompt"], "did the user check out?")

        second = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(second.status_code, 200)

        statuses = {str(s.id): s.status for s in ReplayScannerPromptSuggestion.objects.all()}
        self.assertEqual(statuses[first.json()["id"]], SuggestionStatus.SUPERSEDED)
        self.assertEqual(statuses[second.json()["id"]], SuggestionStatus.PENDING)

    def test_generate_requires_rated_observations(self) -> None:
        resp = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(ReplayScannerPromptSuggestion.objects.exists())

    def test_quality_flag_off_hides_endpoints(self) -> None:
        # `replay-vision-quality` gates the sub-feature even when product-level `replay-vision` is on.
        self._create_rated_observation("sess-1", True)

        def _flags(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_key != "replay-vision-quality"

        with patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", side_effect=_flags):
            current_resp = self.client.get(self._suggestions_url("current/"))
            generate_resp = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(current_resp.status_code, 404, current_resp.content)
        self.assertEqual(generate_resp.status_code, 404, generate_resp.content)
        self.assertFalse(ReplayScannerPromptSuggestion.objects.exists())

    def test_current_reports_staleness_when_ratings_change(self) -> None:
        observation = self._create_rated_observation("sess-1", False, "should be yes")
        self.client.post(self._suggestions_url("generate/"))

        fresh = self.client.get(self._suggestions_url("current/")).json()
        self.assertFalse(fresh["stale"])
        self.assertEqual(fresh["rated_count"], 1)
        self.assertIsNotNone(fresh["suggestion"])

        label = ReplayObservationLabel.objects.get(observation=observation)
        label.is_correct = True
        label.feedback = ""
        label.save()

        stale = self.client.get(self._suggestions_url("current/")).json()
        self.assertTrue(stale["stale"])

    def test_apply_writes_prompt_and_bumps_scanner_version(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        version_before = ReplayScanner.objects.get(id=self.scanner.id).scanner_version

        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/apply/"))
        self.assertEqual(resp.status_code, 200, resp.json())

        scanner = ReplayScanner.objects.get(id=self.scanner.id)
        self.assertEqual(
            scanner.scanner_config["prompt"],
            "Did the user place an order? Only answer yes on an order confirmation.",
        )
        self.assertEqual(scanner.scanner_version, version_before + 1)
        body = resp.json()
        self.assertEqual(body["status"], "applied")
        self.assertIsNotNone(body["applied_at"])

    def test_apply_rejects_non_pending_and_version_mismatched_suggestions(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        superseded_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        dismissed_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        self.client.post(self._suggestions_url(f"{dismissed_id}/dismiss/"))
        pending_id = self.client.post(self._suggestions_url("generate/")).json()["id"]

        # A stale tab submitting the superseded suggestion must not roll the prompt back.
        resp = self.client.post(self._suggestions_url(f"{superseded_id}/apply/"))
        self.assertEqual(resp.status_code, 400)

        # A dismissed suggestion is a rejected prompt; applying it must not revive it.
        resp = self.client.post(self._suggestions_url(f"{dismissed_id}/apply/"))
        self.assertEqual(resp.status_code, 400)

        # The prompt changed (version bump) since the pending suggestion was generated.
        self.scanner.scanner_config = {**self.scanner.scanner_config, "prompt": "edited by hand"}
        self.scanner.save()
        resp = self.client.post(self._suggestions_url(f"{pending_id}/apply/"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ReplayScanner.objects.get(id=self.scanner.id).scanner_config["prompt"], "edited by hand")

    def test_dismiss_marks_suggestion_dismissed(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]

        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/dismiss/"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "dismissed")

    def test_apply_rejects_prompt_failing_scanner_config_validation(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        self.mock_generate.return_value = _LlmPromptSuggestion(suggested_prompt="x" * 20_001, rationale="too long")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        prompt_before = ReplayScanner.objects.get(id=self.scanner.id).scanner_config.get("prompt")

        # The edit endpoint caps prompt length; this write boundary must enforce the same rules.
        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/apply/"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ReplayScanner.objects.get(id=self.scanner.id).scanner_config.get("prompt"), prompt_before)

    def test_dismiss_rejects_applied_suggestion(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        self.client.post(self._suggestions_url(f"{suggestion_id}/apply/"))

        # Dismissing the applied suggestion would mark the scanner's live prompt as rejected.
        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/dismiss/"))
        self.assertEqual(resp.status_code, 400)
        suggestion = ReplayScannerPromptSuggestion.objects.get(id=suggestion_id)
        self.assertEqual(suggestion.status, SuggestionStatus.APPLIED)

    def test_generate_marks_no_change_when_model_returns_current_prompt(self) -> None:
        self._create_rated_observation("sess-1", True)
        self.canned = _LlmPromptSuggestion(
            suggested_prompt="did the user check out?",
            rationale="The prompt already handles the rated sessions well.",
        )

        resp = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["status"], "no_change")

    def test_dismissed_rewrites_feed_the_next_generation(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        self.client.post(self._suggestions_url(f"{suggestion_id}/dismiss/"))

        self.client.post(self._suggestions_url("generate/"))

        user_content = self.mock_agentic.call_args.kwargs["user_content"]
        self.assertIn("Previously rejected rewrites", user_content)
        self.assertIn("Did the user place an order? Only answer yes on an order confirmation.", user_content)

    def test_daily_refresh_gates(self) -> None:
        # No ratings at all: nothing to generate from.
        self.assertEqual(refresh_prompt_suggestion_if_stale(self.scanner), "no_ratings")

        # Ratings but no suggestion yet: generate immediately.
        self._create_rated_observation("sess-1", False, "should be yes")
        self.assertEqual(refresh_prompt_suggestion_if_stale(self.scanner), "generated")

        # Same rated set: skip regardless of age.
        self.assertEqual(refresh_prompt_suggestion_if_stale(self.scanner), "ratings_unchanged")

        # Ratings changed but the newest suggestion is under a day old: wait.
        self._create_rated_observation("sess-2", True)
        self.assertEqual(refresh_prompt_suggestion_if_stale(self.scanner), "refreshed_recently")

        # Ratings changed and the newest suggestion is old enough: regenerate.
        ReplayScannerPromptSuggestion.objects.update(created_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(refresh_prompt_suggestion_if_stale(self.scanner), "generated")
        self.assertEqual(ReplayScannerPromptSuggestion.objects.count(), 2)

    def test_falls_back_to_single_shot_when_the_agent_fails(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        self.mock_agentic.side_effect = RuntimeError("provider hiccup")

        resp = self.client.post(self._suggestions_url("generate/"))

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["status"], "pending")
        self.mock_generate.assert_called_once()

    def test_mutations_require_editor_access(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_resource",
            side_effect=lambda resource, required_level=None, **_: required_level != "editor",
        ):
            resp = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ReplayScannerPromptSuggestion.objects.exists())
