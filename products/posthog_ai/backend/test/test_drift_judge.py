from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.posthog_ai.backend.services.drift_judge import DriftJudgement, judge_drift


class TestDriftJudge(BaseTest):
    def test_empty_narrative_returns_no_drift(self) -> None:
        verdict = judge_drift("")
        self.assertIsInstance(verdict, DriftJudgement)
        self.assertFalse(verdict.drift_detected)
        self.assertEqual(verdict.severity, "none")
        self.assertFalse(verdict.is_emit_worthy)

    @patch("products.posthog_ai.backend.services.drift_judge.MaxChatLLM", None)
    def test_llm_unavailable_falls_back_safely(self) -> None:
        verdict = judge_drift("Activation dropped from 41% to 28% week-over-week.")
        self.assertFalse(verdict.drift_detected)
        self.assertEqual(verdict.severity, "none")
        self.assertIn("offline", verdict.summary)

    def test_significant_drift_is_emit_worthy(self) -> None:
        with patch("products.posthog_ai.backend.services.drift_judge.MaxChatLLM") as mock_cls:
            instance = MagicMock()
            instance.complete_structured.return_value = {
                "drift_detected": True,
                "severity": "significant",
                "summary": "Activation dropped by 30%, sustained for 3+ days.",
            }
            mock_cls.return_value = instance
            verdict = judge_drift("Activation rate dropped from 41.3% to 28.7% over the last 7 days.")
        self.assertTrue(verdict.is_emit_worthy)
        self.assertEqual(verdict.severity, "significant")

    def test_unknown_severity_clamped_to_none(self) -> None:
        with patch("products.posthog_ai.backend.services.drift_judge.MaxChatLLM") as mock_cls:
            instance = MagicMock()
            instance.complete_structured.return_value = {
                "drift_detected": True,
                "severity": "catastrophic",
                "summary": "Made up severity.",
            }
            mock_cls.return_value = instance
            verdict = judge_drift("Some narrative")
        self.assertEqual(verdict.severity, "none")
        self.assertFalse(verdict.is_emit_worthy)
