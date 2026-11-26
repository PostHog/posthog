from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class TestRetireSlackDevApp(NonAtomicTestMigrations):
    app = "mcp_store"
    migrate_from = "0033_linked_user_integration_and_auto_connect_opt_out"
    migrate_to = "0034_retire_slack_dev_app"

    def setUpBeforeMigration(self, apps: Any) -> None:
        MCPServerTemplate = apps.get_model("mcp_store", "MCPServerTemplate")
        MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")
        MCPGatewayServer = apps.get_model("mcp_store", "MCPGatewayServer")
        dev_template = MCPServerTemplate.objects.create(
            name="Slack via PostHog (dev)",
            url="https://mcp.slack.com/mcp",
            auth_type="oauth",
            is_active=True,
            oauth_credentials_source="slack_dev_app",
        )
        other_template = MCPServerTemplate.objects.create(
            name="Linear", url="https://mcp.linear.example.com/mcp", auth_type="oauth", is_active=True
        )
        self.dev_installation_id = MCPServerInstallation.objects.create(
            team_id=self.team.id,
            user_id=self.user.id,
            template=dev_template,
            url=dev_template.url,
            display_name="Slack via PostHog (dev)",
            auth_type="oauth",
            sensitive_configuration={"access_token": "xoxp-dev", "refresh_token": "xoxe-dev", "pending": "kept"},
        ).id
        self.other_installation_id = MCPServerInstallation.objects.create(
            team_id=self.team.id,
            user_id=self.user.id,
            template=other_template,
            url=other_template.url,
            auth_type="oauth",
            sensitive_configuration={"access_token": "other-token"},
        ).id
        self.gateway_server_id = MCPGatewayServer.objects.create(
            team_id=self.team.id, name="Slack via PostHog (dev)", url=dev_template.url, template=dev_template
        ).id
        self.dev_template_id = dev_template.id

    def test_moves_the_template_to_the_production_app_and_revokes_dev_tokens(self) -> None:
        apps = self.apps
        assert apps is not None
        MCPServerTemplate = apps.get_model("mcp_store", "MCPServerTemplate")
        MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")
        MCPGatewayServer = apps.get_model("mcp_store", "MCPGatewayServer")

        template = MCPServerTemplate.objects.get(id=self.dev_template_id)
        assert (template.oauth_credentials_source, template.name, template.is_active) == ("slack_app", "Slack", False)
        dev_installation = MCPServerInstallation.objects.get(id=self.dev_installation_id)
        sensitive = dev_installation.sensitive_configuration
        assert "access_token" not in sensitive and "refresh_token" not in sensitive
        assert sensitive["pending"] == "kept"
        assert sensitive["needs_reauth"]
        assert dev_installation.display_name == "Slack"
        assert MCPGatewayServer.objects.get(id=self.gateway_server_id).name == "Slack"
        other = MCPServerInstallation.objects.get(id=self.other_installation_id)
        assert other.sensitive_configuration == {"access_token": "other-token"}
