from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Drop the foreign key on endpoints_endpoint.saved_query_id, which nothing owns any more.

    0012 took `saved_query` out of Django state with database_operations=[], which left the
    column for rollback safety. That was the intent, and it is correct for a column. The
    foreign key to posthog_datawarehousesavedquery stayed with it, and no later migration
    removes it.

    A parent delete stops cascading into a relation Django cannot see. The constraint is
    DEFERRABLE INITIALLY DEFERRED with NO ACTION, so deleting a saved query finishes its
    cascade and Postgres then rejects the transaction at COMMIT.

    The column stays. Only the constraint goes.
    """

    dependencies = [
        ("endpoints", "0033_alter_endpointversion_saved_query"),
    ]

    operations = [
        DropForeignKey("endpoints_endpoint", column="saved_query_id"),
    ]
