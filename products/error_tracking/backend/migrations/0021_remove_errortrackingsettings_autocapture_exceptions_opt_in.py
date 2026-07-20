from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0020_errortrackingsettings_autocapture_exceptions_opt_in"),
    ]

    # State-only removal: the column stays in Postgres so a rollback deploy keeps working.
    # A later migration may DROP COLUMN once a full deploy cycle has passed.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="errortrackingsettings",
                    name="autocapture_exceptions_opt_in",
                ),
            ],
            database_operations=[],
        ),
    ]
