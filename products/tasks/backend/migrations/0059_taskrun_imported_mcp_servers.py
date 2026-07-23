from django.db import migrations

import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0058_taskthreadmessage_agent_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="imported_mcp_servers",
            field=posthog.helpers.encrypted_fields.EncryptedJSONStringField(
                blank=True,
                default=None,
                help_text="Client-imported MCP server configs (type/name/url/headers) to make available in the sandbox",
                null=True,
            ),
        ),
    ]
