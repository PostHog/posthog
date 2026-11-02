from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0191_repin_qualys_vmdr_api_version_6_0"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="credentials_integration_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
