import django.db.models.deletion
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # Required for AddIndexConcurrently

    dependencies = [
        ("data_warehouse", "0014_mat_view_credential_deletion"),
        ("endpoints", "0008_endpoint_last_executed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="cache_age_seconds",
            field=models.IntegerField(
                blank=True, help_text="Cache age in seconds. If null, uses default interval-based caching.", null=True
            ),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="description",
            field=models.TextField(blank=True, default="", help_text="Optional description for this endpoint version"),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="is_materialized",
            field=models.BooleanField(default=False, help_text="Whether this version's query results are materialized"),
        ),
        migrations.AddField(
            model_name="endpointversion",
            name="saved_query",
            field=models.ForeignKey(
                blank=True,
                db_index=False,  # We'll add the index concurrently below
                help_text="The underlying materialized view for this version",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="endpoint_versions",
                to="data_warehouse.datawarehousesavedquery",
            ),
        ),
        AddIndexConcurrently(
            model_name="endpointversion",
            index=models.Index(fields=["saved_query"], name="endpointvers_saved_q_0dc3_idx"),
        ),
    ]
