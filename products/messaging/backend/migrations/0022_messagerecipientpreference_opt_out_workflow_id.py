from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0021_provider_import_run_temporary_api_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="messagerecipientpreference",
            name="opt_out_workflow_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
