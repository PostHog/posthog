# Generated migration for adding configuration fields to EndpointVersion

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0008_endpoint_last_executed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="cache_age_seconds",
            field=models.IntegerField(
                default=300,
                help_text="Cache age in seconds when this version was created",
            ),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="is_materialized",
            field=models.BooleanField(
                default=False,
                help_text="Whether this version's query results are materialized",
            ),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="sync_frequency",
            field=models.CharField(
                max_length=20,
                null=True,
                blank=True,
                help_text="Sync frequency for materialization (hourly, daily, weekly)",
            ),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="last_materialized_at",
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text="When this version was last materialized",
            ),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="materialization_error",
            field=models.TextField(
                null=True,
                blank=True,
                help_text="Error message from last materialization attempt",
            ),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="saved_query",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=models.SET_NULL,
                to="data_warehouse.datawarehousesavedquery",
                related_name="endpoint_versions",
                help_text="The underlying materialized view for this version",
            ),
        ),
    ]
