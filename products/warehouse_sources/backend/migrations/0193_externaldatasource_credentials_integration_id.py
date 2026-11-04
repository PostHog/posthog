from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0192_repin_loop_returns_api_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="credentials_integration_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
