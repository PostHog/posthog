from django.db import migrations

_DEV_SOURCE = "slack_dev_app"
_DEV_NAME = "Slack via PostHog (dev)"
_TOKEN_KEYS = ("access_token", "refresh_token", "token_retrieved_at", "expires_in")


def retire_slack_dev_app(apps, schema_editor):
    """Move the Slack MCP template off the retired development Slack app.

    The code no longer knows the `slack_dev_app` credential source, so a template that keeps it cannot authorize or
    refresh. A token that the development app issued must not keep working after its project allowlist is gone, so
    each installation loses its token and must connect again through the production app. The template stays
    inactive until the catalog sync probes the production app and activates it.
    """
    MCPServerTemplate = apps.get_model("mcp_store", "MCPServerTemplate")
    MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")
    MCPGatewayServer = apps.get_model("mcp_store", "MCPGatewayServer")

    for template in MCPServerTemplate.objects.filter(oauth_credentials_source=_DEV_SOURCE):
        for installation in MCPServerInstallation.objects.filter(template=template):
            sensitive = {
                key: value
                for key, value in (installation.sensitive_configuration or {}).items()
                if key not in _TOKEN_KEYS
            }
            sensitive["needs_reauth"] = True
            installation.sensitive_configuration = sensitive
            if installation.display_name == _DEV_NAME:
                installation.display_name = "Slack"
            installation.save(update_fields=["sensitive_configuration", "display_name", "updated_at"])
        MCPGatewayServer.objects.filter(template=template, name=_DEV_NAME).update(name="Slack")
        template.oauth_credentials_source = "slack_app"
        template.name = "Slack"
        template.is_active = False
        template.save(update_fields=["oauth_credentials_source", "name", "is_active", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0033_linked_user_integration_and_auto_connect_opt_out"),
    ]

    operations = [
        migrations.RunPython(retire_slack_dev_app, migrations.RunPython.noop, elidable=True),
    ]
