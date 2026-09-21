from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0140_signalreportcheck_soak_minutes_and_more"),
    ]

    operations = [
        # The column is NOT NULL with no database default, and the next release stops naming it in
        # INSERTs. Drop the constraint in the same migration that takes the field out of model state,
        # so a pod on either release can still write an emission row. The column itself goes in a
        # follow-up migration, one deploy cycle later.
        migrations.RunSQL(
            sql="ALTER TABLE signals_signalscoutemission ALTER COLUMN weight DROP NOT NULL;",
            reverse_sql="ALTER TABLE signals_signalscoutemission ALTER COLUMN weight SET NOT NULL;",
        ),
        untrack_field("signalscoutemission", "weight"),
    ]
