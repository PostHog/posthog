from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exports", "0007_alter_exportedasset_export_format")]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="source_authentication",
            field=models.CharField(
                blank=True,
                choices=[
                    ("session", "Session"),
                    ("personal_api_key", "Personal API key"),
                    ("oauth_access_token", "OAuth access token"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="exportedasset",
            name="source_credential_id",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
