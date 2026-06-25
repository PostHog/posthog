from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("warehouse_sources", "0042_dedupe_live_backing_tables"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="datawarehousetable",
                    constraint=models.UniqueConstraint(
                        fields=["team", "name"],
                        condition=Q(external_data_source__isnull=True) & (Q(deleted=False) | Q(deleted__isnull=True)),
                        name="unique_live_self_managed_dwh_table",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_live_self_managed_dwh_table",
                    table_name="posthog_datawarehousetable",
                    columns="(team_id, name)",
                    unique=True,
                    where="WHERE external_data_source_id IS NULL AND (deleted = false OR deleted IS NULL)",
                ),
            ],
        ),
    ]
