from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.feedback_themes import (
    _LlmFeedbackThemes,
    _LlmTheme,
    refresh_feedback_themes_if_stale,
    theme_lines,
)
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.prompt_suggestions import _LlmPromptSuggestion, generate_prompt_suggestion
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_CANNED_THEMES = _LlmFeedbackThemes(
    themes=[
        _LlmTheme(theme="Review page mistaken for confirmation", count=5, examples=["it was only the review step"]),
        _LlmTheme(theme="Coupon banner read as an error", count=2, examples=[]),
    ]
)


class TestFeedbackThemes(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.summarize_patcher = patch(
            "products.replay_vision.backend.feedback_themes._summarize", return_value=_CANNED_THEMES
        )
        self.mock_summarize = self.summarize_patcher.start()

    def tearDown(self) -> None:
        self.summarize_patcher.stop()
        super().tearDown()

    def _rate(self, session_id: str, is_correct: bool, feedback: str = "") -> ReplayObservation:
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=session_id,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_result={"model_output": {"verdict": "no", "confidence": 0.9, "scanner_type": "monitor"}},
        )
        ReplayObservationLabel.objects.create(observation=observation, is_correct=is_correct, feedback=feedback)
        return observation

    def _refresh(self) -> str:
        return refresh_feedback_themes_if_stale(self.scanner, distinct_id="test-user")

    def test_generates_then_skips_until_feedback_changes(self) -> None:
        for i in range(3):
            self._rate(f"sess-{i}", False, f"feedback {i}")

        self.assertEqual(self._refresh(), "generated")
        assert self.scanner.feedback_themes is not None
        self.assertEqual(self.scanner.feedback_themes["feedback_count"], 3)
        self.assertEqual(self.scanner.feedback_themes["themes"][0]["theme"], "Review page mistaken for confirmation")
        self.assertEqual(self.scanner.feedback_themes["themes"][0]["count"], 5)

        self.assertEqual(self._refresh(), "unchanged")
        self.assertEqual(self.mock_summarize.call_count, 1)

        self._rate("sess-3", False, "another failure")
        self.assertEqual(self._refresh(), "generated")
        self.assertEqual(self.mock_summarize.call_count, 2)
        self.assertEqual(self.scanner.feedback_themes["feedback_count"], 4)

    def test_below_threshold_skips_model_and_clears_stale_themes(self) -> None:
        # Thumbs-up notes and empty thumbs-down feedback don't count toward the threshold.
        self._rate("sess-up", True, "nice catch")
        self._rate("sess-empty", False, "")
        self._rate("sess-down", False, "only real comment")

        self.assertEqual(self._refresh(), "too_few_comments")
        self.mock_summarize.assert_not_called()
        self.assertIsNone(self.scanner.feedback_themes)

        # Themes cached from a richer feedback set are cleared once the set shrinks below the threshold.
        self.scanner.feedback_themes = {"themes": [{"theme": "Old", "count": 3, "examples": []}], "fingerprint": "old"}
        self.scanner.save(update_fields=["feedback_themes"])
        self.assertEqual(self._refresh(), "cleared")
        self.scanner.refresh_from_db()
        self.assertIsNone(self.scanner.feedback_themes)
        self.mock_summarize.assert_not_called()

    def test_generate_suggestion_refreshes_themes_and_briefs_the_model_with_them(self) -> None:
        for i in range(3):
            self._rate(f"sess-{i}", False, f"feedback {i}")
        with patch(
            "products.replay_vision.backend.prompt_suggestions._generate_agentic",
            return_value=_LlmPromptSuggestion(suggested_prompt="new prompt", rationale="tightened"),
        ) as mock_agentic:
            generate_prompt_suggestion(self.scanner)
        user_content = mock_agentic.call_args.kwargs["user_content"]
        self.assertIn("Recurring failure modes summarized from the team's feedback", user_content)
        self.assertIn("- Review page mistaken for confirmation (5 comments)", user_content)
        self.scanner.refresh_from_db()
        assert self.scanner.feedback_themes is not None
        self.assertEqual(self.scanner.feedback_themes["feedback_count"], 3)

    def test_theme_refresh_failure_does_not_block_suggestion_generation(self) -> None:
        for i in range(3):
            self._rate(f"sess-{i}", False, f"feedback {i}")
        self.mock_summarize.side_effect = RuntimeError("provider down")
        with patch(
            "products.replay_vision.backend.prompt_suggestions._generate_agentic",
            return_value=_LlmPromptSuggestion(suggested_prompt="new prompt", rationale="tightened"),
        ):
            suggestion = generate_prompt_suggestion(self.scanner)
        self.assertEqual(suggestion.suggested_prompt, "new prompt")
        self.scanner.refresh_from_db()
        self.assertIsNone(self.scanner.feedback_themes)

    @parameterized.expand(
        [
            ("no_cache", None),
            ("empty_themes", {"themes": [], "fingerprint": "x"}),
            ("themes_not_a_list", {"themes": "review page"}),
            ("cache_not_a_dict", ["review page"]),
        ]
    )
    def test_theme_lines_empty_for_missing_or_malformed_cache(self, _name: str, cached: object) -> None:
        self.scanner.feedback_themes = cached
        self.assertEqual(theme_lines(self.scanner), [])

    def test_scanner_api_exposes_themes_without_fingerprint(self) -> None:
        detail_url = f"{self.scanners_url}{self.scanner.id}/"
        self.assertIsNone(self.client.get(detail_url).json()["feedback_themes"])

        self.scanner.feedback_themes = {
            "themes": [{"theme": "Review page mistaken for confirmation", "count": 5, "examples": ["a quote"]}],
            "feedback_count": 5,
            "fingerprint": "abc",
            "generated_at": "2026-07-01T00:00:00+00:00",
        }
        self.scanner.save(update_fields=["feedback_themes"])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["feedback_themes"]
        self.assertEqual(payload["themes"][0]["theme"], "Review page mistaken for confirmation")
        self.assertEqual(payload["feedback_count"], 5)
        self.assertNotIn("fingerprint", payload)
