from django.db import migrations

from posthog.helpers.encrypted_fields import EncryptedTextField


class Migration(migrations.Migration):
    dependencies = [
        ("managed_warehouse", "0007_drop_orphaned_duckgresserver_team_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="duckgresserver",
            name="trino_password",
            field=EncryptedTextField(blank=True, max_length=500, null=True),
        ),
    ]
