from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.management.commands.migrate_ses_tenants import migrate_ses_tenants
from posthog.models.integration import Integration

from products.workflows.backend.facade.api import ensure_sandbox_email_sender
from products.workflows.backend.tasks.ses_tenant_state import reconcile_ses_tenant_states


@override_settings(
    WORKFLOWS_SANDBOX_SENDER_DOMAIN="sandbox.example.com",
    SES_SANDBOX_FROM_ADDRESS="hello@sandbox.example.com",
    SES_SANDBOX_TENANT_NAME="posthog-sandbox",
)
class TestSandboxSenderLifecycleExclusions(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self.sandbox_row = Integration.objects.get(
                team_id=self.team.id, id=ensure_sandbox_email_sender(self.team.id).integration_id
            )

    @patch("posthog.management.commands.migrate_ses_tenants.boto3.client")
    def test_tenant_migration_skips_the_sandbox_sender(self, boto3_client: MagicMock) -> None:
        counts = migrate_ses_tenants(team_ids=[self.team.id], domains=[])

        assert counts.tenants == 0
        boto3_client.assert_not_called()

    @patch("products.workflows.backend.tasks.ses_tenant_state.SESProvider")
    @patch("products.workflows.backend.tasks.ses_tenant_state.sync_ses_tenant_state")
    def test_tenant_state_sweep_skips_the_sandbox_sender(
        self, sync_ses_tenant_state: MagicMock, _ses_provider: MagicMock
    ) -> None:
        reconcile_ses_tenant_states()

        swept_team_ids = [call.args[0] for call in sync_ses_tenant_state.call_args_list]
        assert self.team.id not in swept_team_ids

    @patch("posthog.tasks.integrations.delete_ses_identity_if_unused")
    def test_deleting_a_project_with_a_sandbox_sender_keeps_the_shared_identity(
        self, delete_identity_task: MagicMock
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.team.delete()

        assert not Integration.objects.filter(pk=self.sandbox_row.pk).exists()
        delete_identity_task.delay.assert_not_called()
