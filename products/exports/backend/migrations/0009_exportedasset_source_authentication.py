from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exports", "0008_exportedasset_source_personal_api_key_id")]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="source_authentication",
            field=models.CharField(
                blank=True,
                choices=[
                    ("session", "Session"),
                    ("personal_api_key", "Personal Api Key"),
                    ("oauth_access_token", "Oauth Access Token"),
                    ("trusted_system", "Trusted System"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="exportedasset",
            name="source_oauth_access_token_id",
            field=models.CharField(blank=True, max_length=36, null=True),
        ),
    ]
