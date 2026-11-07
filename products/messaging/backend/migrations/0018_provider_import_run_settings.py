from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0017_provider_import_run_temporary_api_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="providerimportrun",
            name="settings",
            field=models.JSONField(default=dict),
        ),
    ]
