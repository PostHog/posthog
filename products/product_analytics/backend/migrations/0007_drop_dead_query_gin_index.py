from django.db import migrations

from posthog.migration_helpers.concurrent_index import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index operations cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("product_analytics", "0006_insightvariable_values_query_connection_id"),
    ]

    operations = [
        # `posthog_dashboarditem_query_gin` is a `jsonb_ops` GIN index on the whole
        # `query` column. Its only reader filters the column with `icontains`, which
        # renders `query::text ILIKE '%...%'` — a text match a jsonb GIN index cannot
        # serve. No plan picks the index, so it only adds write cost on every insight
        # save. The reverse recreates the original index shape.
        DropIndexConcurrently(
            index_name="posthog_dashboarditem_query_gin",
            table_name="posthog_dashboarditem",
            columns="(query jsonb_ops)",
            using="gin",
        ),
    ]
