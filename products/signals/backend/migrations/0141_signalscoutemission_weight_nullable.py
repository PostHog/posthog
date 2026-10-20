from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0140_signalreportcheck_soak_minutes_and_more"),
    ]

    operations = [
        # Phase 1 of retiring the column. It is NOT NULL with no database default, and the release
        # that untracks the field stops naming it in INSERTs, so the constraint has to go first.
        migrations.RunSQL(
            sql="ALTER TABLE signals_signalscoutemission ALTER COLUMN weight DROP NOT NULL;",
            reverse_sql="ALTER TABLE signals_signalscoutemission ALTER COLUMN weight SET NOT NULL;",
        ),
    ]
