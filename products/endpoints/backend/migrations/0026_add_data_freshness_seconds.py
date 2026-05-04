from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0025_alter_endpoint_created_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="data_freshness_seconds",
            field=models.IntegerField(
                default=86400,
                help_text="How fresh the data should be, in seconds. Controls cache TTL and materialization sync frequency.",
            ),
        ),
    ]
