from posthog.test.base import BaseTest

from posthog.integrations import IntegrationManager
from posthog.models.integration import Integration

from products.slack_app.backend.models import SlackChannelSettings, SlackSettings, ThreadJoinMode
from products.slack_app.backend.services.integration_references import store_integration_id

SLACK_TEAM_ID = "T12345"


class TestSlackAppIntegrationHooks(BaseTest):
    def test_deleting_an_install_keeps_the_other_settings_that_point_at_it(self) -> None:
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id=SLACK_TEAM_ID, sensitive_config={"access_token": "xoxb"}
        )
        personal = SlackSettings.objects.create(
            slack_workspace_id=SLACK_TEAM_ID,
            slack_user_id="U1",
            default_integration=integration,
            thread_join_mode=ThreadJoinMode.NEVER,
        )
        workspace = SlackSettings.objects.create(
            slack_workspace_id=SLACK_TEAM_ID, default_integration=integration, external_channels_enabled=False
        )
        kept_channel = SlackChannelSettings.objects.create(
            slack_workspace_id=SLACK_TEAM_ID,
            slack_channel_id="C1",
            organization=self.organization,
            default_integration_id=store_integration_id(integration.id),
            default_repository="example/web-app",
        )
        SlackChannelSettings.objects.create(
            slack_workspace_id=SLACK_TEAM_ID,
            slack_channel_id="C2",
            organization=self.organization,
            default_integration_id=store_integration_id(integration.id),
        )

        IntegrationManager.any.with_source_rows().delete(self.team.id, integration.id, ignore_usages=True)

        personal.refresh_from_db()
        workspace.refresh_from_db()
        kept_channel.refresh_from_db()
        assert (personal.default_integration_id, personal.thread_join_mode) == (None, ThreadJoinMode.NEVER)
        assert (workspace.default_integration_id, workspace.external_channels_enabled) == (None, False)
        assert (kept_channel.default_integration_id, kept_channel.default_repository) == (None, "example/web-app")
        assert not SlackChannelSettings.objects.filter(slack_channel_id="C2").exists()
