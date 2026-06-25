from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.logic.wizard_cloud import WIZARD_PR_AGENT_PROMPT
from products.tasks.backend.models import Task


class TestCreateWizardCloudRunWiring(SimpleTestCase):
    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_creates_onboarding_wizard_run_with_readonly_agent_scopes(self, mock_create: MagicMock) -> None:
        # The agent only commits and opens/greens the PR, so it runs with read-only PostHog scopes —
        # the wizard does the integration with its own separate token. wizard_config marks the run so
        # the workflow runs the wizard pre-agent step, and ONBOARDING marks this as an onboarding run.
        team = MagicMock()

        tasks_facade.create_wizard_cloud_run(team=team, user_id=42, repository="acme/app")

        mock_create.assert_called_once_with(
            team=team,
            title="Set up PostHog",
            description=WIZARD_PR_AGENT_PROMPT,
            origin_product=Task.OriginProduct.ONBOARDING,
            user_id=42,
            repository="acme/app",
            create_pr=True,
            mode="background",
            branch=None,
            wizard_config={},
            posthog_mcp_scopes="read_only",
        )
