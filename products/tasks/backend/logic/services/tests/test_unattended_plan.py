import pytest

from posthog.models import User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.logic.services.unattended_plan import unattended_model_access_state

CODEX = UserIntegration.IntegrationKind.CODEX
CLAUDE = UserIntegration.IntegrationKind.CLAUDE


@pytest.mark.django_db
class TestUnattendedModelAccessState:
    @pytest.mark.parametrize(
        "runtime_adapter,kind,status,employee,expected",
        [
            ("codex", CODEX, "connected", False, {"codex_model_access": "own-subscription"}),
            ("codex", CODEX, "reauth_required", False, {}),
            ("codex", None, None, False, {}),
            ("claude", CODEX, "connected", True, {}),
            (None, CODEX, "connected", False, {}),
            ("claude", CLAUDE, "connected", True, {"claude_model_access": "own-subscription"}),
            ("claude", CLAUDE, "connected", False, {}),
            ("claude", CLAUDE, "reauth_required", True, {}),
            ("codex", CLAUDE, "connected", True, {}),
        ],
    )
    def test_only_a_connected_plan_matching_the_harness_bills_the_run(
        self, runtime_adapter, kind, status, employee, expected
    ):
        user = User.objects.create(
            email="owner@posthog.com" if employee else "owner@example.com",
            is_staff=employee,
            is_email_verified=employee,
        )
        if kind is not None:
            UserIntegration.objects.create(user=user, kind=kind, integration_id="acct", config={"status": status})

        assert unattended_model_access_state(user, runtime_adapter=runtime_adapter) == expected
