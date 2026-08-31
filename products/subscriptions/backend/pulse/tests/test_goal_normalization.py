from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from products.subscriptions.backend.pulse.contracts import GoalNormalizationInput
from products.subscriptions.backend.pulse.goal_normalization import GoalNormalizationOutput, normalize_goal_with_model


class TestNormalizeGoalWithModel(SimpleTestCase):
    @patch("products.subscriptions.backend.pulse.goal_normalization.MaxChatOpenAI")
    def test_returns_a_locally_validated_narrower_goal(self, chat: Mock) -> None:
        chat.return_value.with_structured_output.return_value.invoke.return_value = GoalNormalizationOutput(
            goal_statement="Increase activation by improving onboarding",
            decision_constraints=["Keep the existing signup flow"],
            repositories=["PostHog/posthog"],
            metrics=["activation"],
            artifact_types=["draft_pr"],
            permissions=["repository:write"],
        )

        result = normalize_goal_with_model(
            team=Mock(),
            user=Mock(),
            source=GoalNormalizationInput(
                original_prompt="Find and implement an onboarding improvement",
                repositories=["PostHog/posthog"],
                metrics=["activation", "retention"],
                artifact_types=["draft_pr", "experiment_draft"],
                permissions=["repository:write", "experiment:create"],
            ),
            subscription_id=7,
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.goal_statement, "Increase activation by improving onboarding")
        self.assertEqual(result.decision_constraints, ["Keep the existing signup flow"])
        self.assertEqual(result.model_version, "gpt-4.1")

    @patch("products.subscriptions.backend.pulse.goal_normalization.MaxChatOpenAI")
    def test_falls_back_when_the_model_widens_authority(self, chat: Mock) -> None:
        chat.return_value.with_structured_output.return_value.invoke.return_value = GoalNormalizationOutput(
            goal_statement="Ship the change everywhere",
            repositories=["PostHog/private"],
            permissions=["repository:admin"],
        )

        result = normalize_goal_with_model(
            team=Mock(),
            user=Mock(),
            source=GoalNormalizationInput(
                original_prompt="Improve activation",
                repositories=["PostHog/posthog"],
                permissions=["repository:write"],
            ),
            subscription_id=7,
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.failure_code, "goal_normalization_widened_consent")
        self.assertEqual(result.goal_statement, "Improve activation")

    @patch("products.subscriptions.backend.pulse.goal_normalization.MaxChatOpenAI")
    def test_falls_back_when_the_model_is_unavailable(self, chat: Mock) -> None:
        chat.return_value.with_structured_output.return_value.invoke.side_effect = TimeoutError

        result = normalize_goal_with_model(
            team=Mock(),
            user=Mock(),
            source=GoalNormalizationInput(original_prompt="  Improve   activation  "),
            subscription_id=7,
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.failure_code, "goal_normalization_failed")
        self.assertEqual(result.goal_statement, "Improve activation")
        self.assertEqual(result.model_version, "gpt-4.1")
