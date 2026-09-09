# Rebuild the saved_query index that migration 0009 left invalid in production.
# 0009 used Django's bare AddIndexConcurrently, so a cancelled build left the
# index with indisvalid = false, which no normal deploy repairs.
# CreateIndexConcurrently drops the invalid leftover before rebuilding, unlike a
# plain rerun. state_operations stays empty because 0009 already recorded the
# index in Django state.

from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("endpoints", "0031_endpointversion_optional_breakdown_properties"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="endpointvers_saved_q_0dc3_idx",
                    table_name="endpoints_endpointversion",
                    columns="(saved_query_id)",
                ),
            ],
        ),
    ]
