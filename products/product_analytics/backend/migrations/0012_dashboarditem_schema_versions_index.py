from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("product_analytics", "0011_dashboarditem_schema_versions")]

    operations = [
        CreateIndexConcurrently(
            index_name="dashboarditem_schema_versions",
            table_name="posthog_dashboarditem",
            columns="(posthog_dashboarditem_schema_versions(query))",
            using="gin",
        ),
    ]
