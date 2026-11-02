import pytest

from posthog.models import User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.logic.services.unattended_plan import unattended_model_access_state


@pytest.mark.django_db
class TestUnattendedModelAccessState:
    @pytest.mark.parametrize(
        "runtime_adapter,status,expected",
        [
            ("codex", "connected", {"codex_model_access": "own-subscription"}),
            ("codex", "reauth_required", {}),
            ("codex", None, {}),
            ("claude", "connected", {}),
            (None, "connected", {}),
        ],
    )
    def test_only_a_connected_plan_matching_the_harness_bills_the_run(self, runtime_adapter, status, expected):
        user = User.objects.create(email="owner@example.com")
        if status is not None:
            UserIntegration.objects.create(
                user=user, kind=UserIntegration.IntegrationKind.CODEX, integration_id="acct", config={"status": status}
            )

        assert unattended_model_access_state(user, runtime_adapter=runtime_adapter) == expected
