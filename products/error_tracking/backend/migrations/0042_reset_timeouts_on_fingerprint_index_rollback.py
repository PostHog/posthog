from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("error_tracking", "0041_errortrackingalertdestination_consecutive_failures_and_more")]

    operations = [
        # Rollback only. Django reverses migrations newest first, so this runs after the concurrent
        # operations in 0043 have turned lock_timeout and statement_timeout off on the shared
        # session. Without it the next reverse migration runs with no bounded lock wait.
        # 0044 covers the same gap on the forward path; neither can cover both, because a migration
        # runs on opposite sides of 0043 in the two directions.
        migrations.RunSQL(
            sql=migrations.RunSQL.noop,
            reverse_sql=["RESET lock_timeout", "RESET statement_timeout"],
        ),
    ]
