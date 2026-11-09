from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0016_add_array_schema_property_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventdefinition",
            name="scheduled_deletion_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="ingestion_stopped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
