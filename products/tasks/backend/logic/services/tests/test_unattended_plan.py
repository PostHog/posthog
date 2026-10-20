import pytest
from unittest.mock import patch

from posthog.models import User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.logic.services.unattended_plan import unattended_model_access_state

FLAG_TARGET = "products.tasks.backend.feature_flags.posthoganalytics.feature_enabled"


@pytest.mark.django_db
class TestUnattendedModelAccessState:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = User.objects.create(email="owner@example.com", distinct_id="owner-distinct-id")

    def _connect_codex(self, status: str) -> None:
        UserIntegration.objects.create(
            user=self.user, kind=UserIntegration.IntegrationKind.CODEX, integration_id="acct", config={"status": status}
        )

    def test_a_connected_plan_bills_a_codex_run(self):
        self._connect_codex("connected")

        with patch(FLAG_TARGET, return_value=True) as flag:
            state = unattended_model_access_state(self.user, organization_id="org", runtime_adapter="codex")

        assert state == {"codex_model_access": "own-subscription"}
        assert flag.call_args.kwargs["distinct_id"] == "owner-distinct-id"

    @pytest.mark.parametrize(
        "runtime_adapter,status,flag_on",
        [
            ("codex", "reauth_required", True),
            ("codex", None, True),
            ("codex", "connected", False),
            ("claude", "connected", True),
            (None, "connected", True),
        ],
    )
    def test_anything_short_of_a_usable_matching_plan_keeps_posthog_credits(self, runtime_adapter, status, flag_on):
        if status is not None:
            self._connect_codex(status)

        with patch(FLAG_TARGET, return_value=flag_on):
            assert (
                unattended_model_access_state(self.user, organization_id="org", runtime_adapter=runtime_adapter) == {}
            )
