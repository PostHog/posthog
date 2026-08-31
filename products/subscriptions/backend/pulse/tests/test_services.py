from django.test import SimpleTestCase

from products.subscriptions.backend.pulse.contracts import GoalNormalizationCandidate, GoalNormalizationInput
from products.subscriptions.backend.pulse.evidence import EvidencePayloadTooLarge, serialize_evidence_payload
from products.subscriptions.backend.pulse.services import (
    action_fingerprint,
    fallback_goal_normalization,
    opportunity_fingerprint,
    stable_action_key,
    validate_goal_normalization,
    validate_snapshot_fields,
)


class TestGoalNormalization(SimpleTestCase):
    def test_rejects_a_candidate_that_widens_server_constraints(self) -> None:
        result = validate_goal_normalization(
            GoalNormalizationCandidate(
                goal_statement="Improve activation",
                decision_constraints=["Use the selected repository."],
                repositories=["other/repository"],
                identities=[],
                metrics=[],
                artifact_types=["draft_pr"],
                permissions=[],
            ),
            GoalNormalizationInput(
                original_prompt="How can we improve activation?",
                repositories=["posthog/posthog"],
                identities=[],
                metrics=[],
                artifact_types=["draft_pr"],
                permissions=[],
            ),
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.failure_code, "goal_normalization_widened_consent")

    def test_fallback_is_bounded_and_deterministic(self) -> None:
        prompt = "A" * 5000

        first = fallback_goal_normalization(prompt)
        second = fallback_goal_normalization(prompt)

        self.assertEqual(first, second)
        self.assertEqual(first.failure_code, "goal_normalization_failed")
        self.assertLessEqual(len(first.goal_statement), 1000)


class TestFingerprinting(SimpleTestCase):
    def test_stable_action_key_uses_only_semantic_measurement_identity(self) -> None:
        original = stable_action_key(
            kind="recommendation",
            normalized_target={"category": "checkout", "surface": "web"},
            metric_name="Checkout completion",
        )

        assert original == stable_action_key(
            kind="recommendation",
            normalized_target={"surface": "web", "category": "checkout"},
            metric_name="  checkout   completion ",
        )
        assert original != stable_action_key(
            kind="recommendation",
            normalized_target={"category": "onboarding", "surface": "web"},
            metric_name="Checkout completion",
        )

    def test_opportunity_key_is_subscription_independent_and_action_key_uses_goal(self) -> None:
        opportunity = opportunity_fingerprint(
            observation_targets={"insight_id": 42, "metric": "activation"}, evidence_ids=["e2", "e1"]
        )

        self.assertEqual(
            opportunity,
            opportunity_fingerprint(
                observation_targets={"metric": "activation", "insight_id": 42}, evidence_ids=["e1", "e2"]
            ),
        )
        self.assertNotEqual(
            action_fingerprint(
                goal_statement="Improve activation",
                kind="recommendation",
                normalized_target={"category": "onboarding"},
                evidence_ids=["e1"],
            ),
            action_fingerprint(
                goal_statement="Improve retention",
                kind="recommendation",
                normalized_target={"category": "onboarding"},
                evidence_ids=["e1"],
            ),
        )


class TestSnapshotValidation(SimpleTestCase):
    def test_rejects_unknown_or_oversized_snapshot_fields(self) -> None:
        with self.assertRaises(ValueError):
            validate_snapshot_fields(
                original_prompt="prompt",
                contexts=[{"dashboard_id": 1, "insight_id": 2}],
                limits={"unknown": 1},
                flags={"allow_draft_pr": True},
            )

    def test_accepts_only_exact_context_and_policy_keys(self) -> None:
        validate_snapshot_fields(
            original_prompt="prompt",
            contexts=[{"insight_id": 1}],
            limits={"max_actions": 1},
            flags={"allow_draft_pr": False},
        )


class TestEvidencePayloads(SimpleTestCase):
    def test_raw_evidence_payloads_are_canonical_and_bounded(self) -> None:
        payload = serialize_evidence_payload({"query": "select 1", "limit": 1})

        assert payload == '{"limit":1,"query":"select 1"}'
        with self.assertRaises(EvidencePayloadTooLarge):
            serialize_evidence_payload({"result": "x" * 70_000})
