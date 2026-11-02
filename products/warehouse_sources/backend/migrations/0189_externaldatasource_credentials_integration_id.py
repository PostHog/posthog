from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0188_reset_trunkio_v2_failing_tests"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="credentials_integration_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
