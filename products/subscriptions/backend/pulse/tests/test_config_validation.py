from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.subscriptions.backend.presentation.serializers import ProactiveSubscriptionConfigSerializer
from products.subscriptions.backend.pulse.contracts import ProactiveConfigInput
from products.subscriptions.backend.pulse.services import validate_proactive_config_input


class TestProactiveConfigValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("free_text_subject", "public_research_subject", "Acme earnings"),
            ("arbitrary_domain", "canonical_domain", "unreviewed.example"),
            ("subject_text", "subject", "Quarterly product news"),
        ]
    )
    def test_rejects_unknown_subject_configuration_fields(self, _name: str, field: str, value: str) -> None:
        serializer = ProactiveSubscriptionConfigSerializer(data={"enabled": True, field: value})

        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_draft_pr_requires_enabled_exact_repository_and_current_authorization(self) -> None:
        errors = validate_proactive_config_input(
            ProactiveConfigInput(
                enabled=False,
                repository="posthog/posthog",
                create_draft_pr=True,
                repository_grant_id=uuid4(),
                public_research_subject_id=None,
            ),
            resource_type="ai_prompt",
            repository_authorized=True,
            subject=None,
        )

        self.assertIn("create_draft_pr", errors)

    def test_research_subject_is_server_selected_not_free_text(self) -> None:
        errors = validate_proactive_config_input(
            ProactiveConfigInput(
                enabled=True,
                repository=None,
                create_draft_pr=False,
                repository_grant_id=None,
                public_research_subject_id=None,
            ),
            resource_type="ai_prompt",
            repository_authorized=False,
            subject=None,
        )

        self.assertEqual(errors, {})

    def test_draft_pr_rejects_a_repository_without_current_authorization(self) -> None:
        errors = validate_proactive_config_input(
            ProactiveConfigInput(
                enabled=True,
                repository="posthog/posthog",
                create_draft_pr=True,
                repository_grant_id=uuid4(),
                public_research_subject_id=None,
            ),
            resource_type="ai_prompt",
            repository_authorized=False,
            subject=None,
        )

        self.assertIn("repository", errors)

    def test_subject_requires_an_eligible_reviewed_record(self) -> None:
        errors = validate_proactive_config_input(
            ProactiveConfigInput(enabled=True, public_research_subject_id=uuid4()),
            resource_type="ai_prompt",
            repository_authorized=False,
            subject=SimpleNamespace(eligible=True, reviewed_at=None, disabled_at=None),
        )

        self.assertIn("public_research_subject_id", errors)
