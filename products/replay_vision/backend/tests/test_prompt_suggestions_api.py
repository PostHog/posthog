from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.rate_limit import AIBurstRateThrottle

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import (
    ReplayScannerPromptSuggestion,
    SuggestionStatus,
)
from products.replay_vision.backend.prompt_suggestions import (
    PromptSuggestionError,
    _LlmPromptSuggestion,
    refresh_prompt_suggestion_if_stale,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_ACCESS_CONTROL_HELPER = "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_resource"


class _PromptSuggestionTestCase(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

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


class TestPromptSuggestions(_PromptSuggestionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.generate_patcher = patch(
            "products.replay_vision.backend.prompt_suggestions._generate",
            return_value=_LlmPromptSuggestion(
                suggested_prompt="Did the user place an order? Only answer yes on an order confirmation.",
                rationale="Tightened the yes condition using the rated sessions.",
            ),
        )
        self.mock_generate = self.generate_patcher.start()

    def tearDown(self) -> None:
        self.generate_patcher.stop()
        super().tearDown()

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

    def test_rating_made_during_generation_still_reads_stale(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")

        def rate_mid_call(**_kwargs) -> _LlmPromptSuggestion:
            self._create_rated_observation("sess-2", True)
            return _LlmPromptSuggestion(suggested_prompt="rewritten", rationale="r")

        self.mock_generate.side_effect = rate_mid_call
        resp = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(resp.status_code, 200, resp.json())

        # The mid-call rating was not in the model input, so the suggestion must read as stale.
        current = self.client.get(self._suggestions_url("current/")).json()
        self.assertTrue(current["stale"])

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

    def test_apply_rejects_superseded_and_version_mismatched_suggestions(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        superseded_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        pending_id = self.client.post(self._suggestions_url("generate/")).json()["id"]

        # A stale tab submitting the superseded suggestion must not roll the prompt back.
        resp = self.client.post(self._suggestions_url(f"{superseded_id}/apply/"))
        self.assertEqual(resp.status_code, 400)

        # The prompt changed (version bump) since the pending suggestion was generated.
        self.scanner.scanner_config = {**self.scanner.scanner_config, "prompt": "edited by hand"}
        self.scanner.save()
        resp = self.client.post(self._suggestions_url(f"{pending_id}/apply/"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ReplayScanner.objects.get(id=self.scanner.id).scanner_config["prompt"], "edited by hand")

    def test_apply_allowed_on_dismissed_then_blocks_reapply(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        self.client.post(self._suggestions_url(f"{suggestion_id}/dismiss/"))

        # The UI offers Apply on a dismissed (change-of-mind) suggestion.
        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/apply/"))
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(
            ReplayScanner.objects.get(id=self.scanner.id).scanner_config["prompt"],
            "Did the user place an order? Only answer yes on an order confirmation.",
        )

        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/apply/"))
        self.assertEqual(resp.status_code, 400)

    def test_dismiss_marks_suggestion_dismissed(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]

        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/dismiss/"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "dismissed")
        self.assertEqual(ReplayScannerPromptSuggestion.objects.get(id=suggestion_id).status, SuggestionStatus.DISMISSED)

    def test_dismiss_rejects_non_pending_suggestions(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        self.client.post(self._suggestions_url(f"{suggestion_id}/apply/"))

        # Dismissing an applied suggestion would feed the live prompt into the "do not propose again" list.
        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/dismiss/"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ReplayScannerPromptSuggestion.objects.get(id=suggestion_id).status, SuggestionStatus.APPLIED)

    def test_generate_marks_no_change_when_model_returns_current_prompt(self) -> None:
        self._create_rated_observation("sess-1", True)
        self.mock_generate.return_value = _LlmPromptSuggestion(
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

        user_content = self.mock_generate.call_args.kwargs["user_content"]
        self.assertIn("Previously rejected rewrites", user_content)
        self.assertIn("Did the user place an order? Only answer yes on an order confirmation.", user_content)

    def test_list_returns_scanner_history_newest_first(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        first_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        second_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        ReplayScannerPromptSuggestion.objects.filter(id=first_id).update(
            created_at=timezone.now() - timedelta(minutes=1)
        )
        sibling = self._create_scanner(name="sibling")
        ReplayScannerPromptSuggestion.objects.create(
            scanner=sibling, team=self.team, suggested_prompt="other scanner's", scanner_version=0
        )

        results = self.client.get(self._suggestions_url()).json()["results"]
        self.assertEqual([row["id"] for row in results], [second_id, first_id])

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

    def test_refresh_backs_off_after_a_failed_generation(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        self.mock_generate.side_effect = PromptSuggestionError("model call failed")

        with self.assertRaises(PromptSuggestionError):
            refresh_prompt_suggestion_if_stale(self.scanner)
        self.assertEqual(self.mock_generate.call_count, 1)

        # Without the backoff the 5-minute sweep would retry the failing LLM call forever.
        self.assertEqual(refresh_prompt_suggestion_if_stale(self.scanner), "backing_off")
        self.assertEqual(self.mock_generate.call_count, 1)

    def test_refresh_reports_not_configured_instead_of_raising(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        self.mock_generate.side_effect = PromptSuggestionError("not configured")
        self.assertEqual(refresh_prompt_suggestion_if_stale(self.scanner), "not_configured")

    @parameterized.expand(["generate", "apply", "dismiss"])
    def test_mutations_require_editor_access(self, action: str) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        prompt_before = ReplayScanner.objects.get(id=self.scanner.id).scanner_config["prompt"]
        url = self._suggestions_url("generate/" if action == "generate" else f"{suggestion_id}/{action}/")

        with patch(
            _ACCESS_CONTROL_HELPER,
            side_effect=lambda resource, required_level=None, **_: required_level != "editor",
        ):
            resp = self.client.post(url)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(ReplayScanner.objects.get(id=self.scanner.id).scanner_config["prompt"], prompt_before)
        self.assertEqual(ReplayScannerPromptSuggestion.objects.count(), 1)
        self.assertEqual(ReplayScannerPromptSuggestion.objects.get(id=suggestion_id).status, SuggestionStatus.PENDING)

    def test_reading_requires_session_recording_access(self) -> None:
        with patch(_ACCESS_CONTROL_HELPER, return_value=False):
            resp = self.client.get(self._suggestions_url("current/"))
        self.assertEqual(resp.status_code, 403)

    def test_generate_is_rate_limited_as_an_ai_endpoint(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        with patch.object(AIBurstRateThrottle, "rate", "1/minute"):
            self.assertEqual(self.client.post(self._suggestions_url("generate/")).status_code, 200)
            self.assertEqual(self.client.post(self._suggestions_url("generate/")).status_code, 429)
        self.assertEqual(ReplayScannerPromptSuggestion.objects.count(), 1)

    def test_cross_team_scanner_and_cross_scanner_suggestion_are_404(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="theirs",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        resp = self.client.get(f"{self.scanners_url}{other_scanner.id}/prompt_suggestions/current/")
        self.assertEqual(resp.status_code, 404)

        # A suggestion on a different scanner must not be actionable through this scanner's URL.
        sibling = self._create_scanner(name="sibling")
        sibling_suggestion = ReplayScannerPromptSuggestion.objects.create(
            scanner=sibling, team=self.team, suggested_prompt="p2", scanner_version=sibling.scanner_version
        )
        resp = self.client.post(self._suggestions_url(f"{sibling_suggestion.id}/apply/"))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(
            ReplayScannerPromptSuggestion.objects.get(id=sibling_suggestion.id).status, SuggestionStatus.PENDING
        )


@override_settings(GEMINI_API_KEY="test-key", REPLAY_VISION_GEMINI_API_KEY="")
class TestPromptSuggestionGenerationFailures(_PromptSuggestionTestCase):
    """Exercises the real `_generate` against a mocked Gemini client: failures must 400, not 500,
    and persist nothing."""

    def setUp(self) -> None:
        super().setUp()
        self._create_rated_observation("sess-1", False, "should be yes")

    @parameterized.expand(
        [
            ("provider_error", None),
            ("empty_response", ""),
            ("invalid_json", "not json"),
            ("blank_prompt", '{"suggested_prompt": "   ", "rationale": "r"}'),
        ]
    )
    def test_generation_failures_return_400_and_persist_nothing(self, name: str, response_text: str | None) -> None:
        with patch("products.replay_vision.backend.prompt_suggestions.genai.Client") as mock_client:
            generate_content = mock_client.return_value.models.generate_content
            if name == "provider_error":
                generate_content.side_effect = RuntimeError("provider down")
            else:
                generate_content.return_value = SimpleNamespace(text=response_text)
            resp = self.client.post(self._suggestions_url("generate/"))

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(ReplayScannerPromptSuggestion.objects.exists())

    def test_generate_without_api_key_is_a_clear_400(self) -> None:
        with override_settings(GEMINI_API_KEY="", REPLAY_VISION_GEMINI_API_KEY=""):
            resp = self.client.post(self._suggestions_url("generate/"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Gemini API key", str(resp.json()))
        self.assertFalse(ReplayScannerPromptSuggestion.objects.exists())
