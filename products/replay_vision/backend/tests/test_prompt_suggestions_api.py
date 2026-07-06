from datetime import timedelta

from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
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

    def _create_classifier_scanner(self) -> ReplayScanner:
        return self._create_scanner(
            name="classifier",
            scanner_type=ScannerType.CLASSIFIER,
            scanner_config={"prompt": "tag the session", "tags": ["bug", "confusion"], "multi_label": True},
            query={"kind": "RecordingsQuery", "filter_test_accounts": True},
            sampling_rate=0.5,
        )

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

    def test_dismiss_marks_suggestion_dismissed(self) -> None:
        self._create_rated_observation("sess-1", False, "should be yes")
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]

        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/dismiss/"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "dismissed")

    def test_generate_stores_validated_parameter_proposals(self) -> None:
        self.scanner = self._create_classifier_scanner()
        self._create_rated_observation("sess-1", False, "should be tagged churn")
        self.canned = _LlmPromptSuggestion(
            suggested_prompt="Tag the session with the right categories.",
            rationale="Adds churn to the vocabulary and narrows the filter.",
            suggested_tags=["bug", "confusion", "churn"],
            suggested_query='{"kind": "RecordingsQuery", "filter_test_accounts": false, "date_from": "-7d"}',
            suggested_sampling_rate=0.25,
        )

        resp = self.client.post(self._suggestions_url("generate/"))

        self.assertEqual(resp.status_code, 200, resp.json())
        body = resp.json()
        self.assertEqual(body["status"], "pending")
        params = body["suggested_parameters"]
        self.assertEqual(params["scanner_config"]["prompt"], "Tag the session with the right categories.")
        self.assertEqual(params["scanner_config"]["tags"], ["bug", "confusion", "churn"])
        # Date bounds are the schedule's business, stripped exactly like the scanner API does on save.
        self.assertEqual(params["query"], {"kind": "RecordingsQuery", "filter_test_accounts": False})
        self.assertEqual(params["sampling_rate"], 0.25)
        self.assertEqual(body["base_parameters"]["scanner_config"]["tags"], ["bug", "confusion"])
        self.assertEqual(body["base_parameters"]["sampling_rate"], 0.5)

    @parameterized.expand(
        [
            ("invalid_query_json", True, {"suggested_query": "not json"}),
            ("query_of_wrong_kind", True, {"suggested_query": '{"kind": "EventsQuery"}'}),
            ("sampling_rate_out_of_range", True, {"suggested_sampling_rate": 1.5}),
            ("blank_tags", True, {"suggested_tags": ["", "  "]}),
            ("tags_on_non_classifier", False, {"suggested_tags": ["bug"]}),
        ]
    )
    def test_invalid_parameter_proposals_fall_back_to_current_values(self, _name, use_classifier, extra) -> None:
        if use_classifier:
            self.scanner = self._create_classifier_scanner()
        self._create_rated_observation("sess-1", False, "should be yes")
        self.canned = _LlmPromptSuggestion(suggested_prompt="A better prompt.", rationale="r", **extra)

        resp = self.client.post(self._suggestions_url("generate/"))

        self.assertEqual(resp.status_code, 200, resp.json())
        params = resp.json()["suggested_parameters"]
        base = resp.json()["base_parameters"]
        # The bad proposal is dropped; only the prompt changes.
        self.assertEqual(params["scanner_config"], {**base["scanner_config"], "prompt": "A better prompt."})
        self.assertEqual(params["query"], base["query"])
        self.assertEqual(params["sampling_rate"], base["sampling_rate"])

    def test_apply_writes_full_parameter_set_and_bumps_version_once(self) -> None:
        self.scanner = self._create_classifier_scanner()
        self._create_rated_observation("sess-1", False, "needs a churn tag")
        self.canned = _LlmPromptSuggestion(
            suggested_prompt="Tag it right.",
            rationale="r",
            suggested_tags=["bug", "confusion", "churn"],
            suggested_query='{"kind": "RecordingsQuery", "filter_test_accounts": false}',
            suggested_sampling_rate=1.0,
        )
        suggestion_id = self.client.post(self._suggestions_url("generate/")).json()["id"]
        version_before = ReplayScanner.objects.get(id=self.scanner.id).scanner_version

        resp = self.client.post(self._suggestions_url(f"{suggestion_id}/apply/"))

        self.assertEqual(resp.status_code, 200, resp.json())
        scanner = ReplayScanner.objects.get(id=self.scanner.id)
        self.assertEqual(scanner.scanner_config["prompt"], "Tag it right.")
        self.assertEqual(scanner.scanner_config["tags"], ["bug", "confusion", "churn"])
        self.assertEqual(scanner.query, {"kind": "RecordingsQuery", "filter_test_accounts": False})
        self.assertEqual(scanner.sampling_rate, 1.0)
        self.assertEqual(scanner.scanner_version, version_before + 1)

    def test_apply_legacy_prompt_only_suggestion_keeps_other_parameters(self) -> None:
        suggestion = ReplayScannerPromptSuggestion.objects.create(
            scanner=self.scanner,
            team=self.team,
            suggested_prompt="legacy rewrite",
            status=SuggestionStatus.PENDING,
            scanner_version=self.scanner.scanner_version,
        )

        resp = self.client.post(self._suggestions_url(f"{suggestion.id}/apply/"))

        self.assertEqual(resp.status_code, 200, resp.json())
        scanner = ReplayScanner.objects.get(id=self.scanner.id)
        self.assertEqual(scanner.scanner_config["prompt"], "legacy rewrite")
        self.assertEqual(scanner.query, {})
        self.assertEqual(scanner.sampling_rate, 1.0)

    def test_apply_with_empty_config_proposal_falls_back_to_prompt_only(self) -> None:
        suggestion = ReplayScannerPromptSuggestion.objects.create(
            scanner=self.scanner,
            team=self.team,
            suggested_prompt="rewrite",
            status=SuggestionStatus.PENDING,
            scanner_version=self.scanner.scanner_version,
            suggested_parameters={"scanner_config": {}},
        )

        resp = self.client.post(self._suggestions_url(f"{suggestion.id}/apply/"))

        self.assertEqual(resp.status_code, 200, resp.json())
        # A malformed empty config must never be written; the prompt-only fallback applies instead.
        self.assertEqual(ReplayScanner.objects.get(id=self.scanner.id).scanner_config, {"prompt": "rewrite"})

    def test_same_prompt_with_parameter_change_is_pending_not_no_change(self) -> None:
        self._create_rated_observation("sess-1", True)
        self.canned = _LlmPromptSuggestion(
            suggested_prompt="did the user check out?",
            rationale="The prompt is fine, but scan fewer sessions.",
            suggested_sampling_rate=0.5,
        )

        resp = self.client.post(self._suggestions_url("generate/"))

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["status"], "pending")
        self.assertEqual(resp.json()["suggested_parameters"]["sampling_rate"], 0.5)

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
