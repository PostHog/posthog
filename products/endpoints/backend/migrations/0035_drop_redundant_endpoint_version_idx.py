from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("endpoints", "0034_drop_orphaned_endpoint_saved_query_fk"),
    ]

    operations = [
        # Duplicates `unique_endpoint_version` on the same (endpoint_id, version) columns.
        # The unique constraint serves every lookup on those columns.
        SafeRemoveIndexConcurrently(
            model_name="endpointversion",
            name="endpoint_version_idx",
        ),
    ]
