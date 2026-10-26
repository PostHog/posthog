from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0170_signalscoutconfig_lifecycle_locked"),
    ]

    operations = [
        # Phase 3: 0142 and 0145 removed both fields from model state, and that release has run for
        # more than one deploy cycle, so no running code names either column.
        migrations.RunSQL(
            sql="ALTER TABLE signals_signalscoutemission DROP COLUMN IF EXISTS weight, DROP COLUMN IF EXISTS confidence;",
            reverse_sql="ALTER TABLE signals_signalscoutemission ADD COLUMN IF NOT EXISTS weight double precision NULL, ADD COLUMN IF NOT EXISTS confidence double precision NULL;",
        ),
    ]
