import pytest
from unittest.mock import patch

from posthog.models import Organization, Team, User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.logic.services.subscription_preferences import (
    set_preferred_model_access,
    unattended_model_access_state,
)

FLAG_TARGET = "products.tasks.backend.feature_flags.posthoganalytics.feature_enabled"


@pytest.mark.django_db
class TestUnattendedModelAccessState:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization, name="test")
        self.user = User.objects.create(email="owner@example.com", distinct_id="owner-distinct-id")

    def _connect_codex(self, status: str = "connected") -> None:
        UserIntegration.objects.create(
            user=self.user, kind=UserIntegration.IntegrationKind.CODEX, integration_id="acct", config={"status": status}
        )

    def _state(self, runtime_adapter: str | None = "codex") -> dict[str, str]:
        return unattended_model_access_state(
            team_id=self.team.id,
            user_id=self.user.id,
            organization_id=str(self.organization.id),
            runtime_adapter=runtime_adapter,
        )

    def test_a_connected_opted_in_plan_bills_a_codex_run(self):
        self._connect_codex()
        set_preferred_model_access(self.team.id, self.user.id, "codex", "own-subscription")

        with patch(FLAG_TARGET, return_value=True) as flag:
            assert self._state() == {"codex_model_access": "own-subscription"}

        assert flag.call_args.kwargs["distinct_id"] == "owner-distinct-id"

    @pytest.mark.parametrize(
        "runtime_adapter,preference,status,flag_on",
        [
            ("codex", None, "connected", True),
            ("codex", "posthog-gateway", "connected", True),
            ("codex", "own-subscription", "reauth_required", True),
            ("codex", "own-subscription", None, True),
            ("codex", "own-subscription", "connected", False),
            ("claude", "own-subscription", "connected", True),
            (None, "own-subscription", "connected", True),
        ],
    )
    def test_anything_short_of_a_usable_matching_plan_keeps_posthog_credits(
        self, runtime_adapter, preference, status, flag_on
    ):
        if status is not None:
            self._connect_codex(status)
        if preference is not None:
            set_preferred_model_access(self.team.id, self.user.id, "codex", preference)
            set_preferred_model_access(self.team.id, self.user.id, "claude", preference)

        with patch(FLAG_TARGET, return_value=flag_on):
            assert self._state(runtime_adapter) == {}
