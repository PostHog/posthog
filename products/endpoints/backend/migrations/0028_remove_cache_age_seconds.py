from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0027_copy_cache_age_to_data_freshness"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="endpointversion", name="cache_age_seconds"),
            ],
            database_operations=[],  # No DB changes - column remains for rollback safety
        ),
    ]
