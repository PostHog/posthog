from django.db import migrations, models

import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0161_task_run_liveness"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentegressregistration",
            name="git_read_grant",
            field=posthog.helpers.encrypted_fields.EncryptedJSONStringField(null=True),
        ),
        migrations.AddField(
            model_name="agentegressregistration",
            name="git_read_grant_version",
            field=models.UUIDField(editable=False, null=True),
        ),
    ]
