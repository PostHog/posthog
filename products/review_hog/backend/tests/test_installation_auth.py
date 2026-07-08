import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from temporalio.exceptions import ApplicationError

from posthog.models.integration import Integration

from products.review_hog.backend.temporal.activities import _installation_auth

# The true network boundary: first_for_team_repository probes GitHub with an authenticated
# GET /repos/{repository} per candidate integration row.
_CAN_ACCESS = "posthog.models.integration.GitHubIntegration.installation_can_access_repository"


class TestInstallationAuth(BaseTest):
    def _integration(self, installation_id: str = "9876543") -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=installation_id,
            # No expires_in/refreshed_at → the stored token is used without a refresh round-trip.
            config={},
            sensitive_config={"access_token": "install-tok"},
            created_by=self.user,
        )

    @patch(_CAN_ACCESS, return_value=True)
    def test_returns_the_token_and_the_github_installation_id(self, _can_access: MagicMock) -> None:
        # The egress budget must key on GitHub's installation id (Integration.integration_id), never
        # the PostHog row pk — several rows can share one installation, which has ONE real budget.
        self._integration(installation_id="9876543")

        token, installation_id = _installation_auth(self.team.id, "PostHog/posthog")

        assert token == "install-tok"
        assert installation_id == "9876543"

    @patch(_CAN_ACCESS, return_value=False)
    def test_no_accessible_installation_raises_retryably(self, _can_access: MagicMock) -> None:
        # The probe can't distinguish "no installation" from a transient GitHub failure, so the error
        # must stay retryable; the genuine misconfig fails fast in validate_github_integration_activity.
        self._integration()

        with pytest.raises(ApplicationError) as err:
            _installation_auth(self.team.id, "PostHog/posthog")

        assert err.value.non_retryable is False
