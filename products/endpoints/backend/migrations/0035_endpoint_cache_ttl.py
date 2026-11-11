from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0034_drop_orphaned_endpoint_saved_query_fk"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="endpointversion",
                    name="data_freshness_seconds",
                    field=models.IntegerField(
                        db_column="data_freshness_seconds",
                        default=86400,
                        help_text="How long direct query results remain in the cache, in seconds.",
                    ),
                ),
                migrations.RenameField(
                    model_name="endpointversion",
                    old_name="data_freshness_seconds",
                    new_name="cache_ttl_seconds",
                ),
            ],
        ),
    ]
