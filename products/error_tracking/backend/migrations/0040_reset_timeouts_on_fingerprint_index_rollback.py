from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("error_tracking", "0039_drop_superseded_fingerprint_constraint")]

    operations = [
        # Rollback only. Django reverses migrations newest first, so this runs after the concurrent
        # operations in 0041 have turned lock_timeout and statement_timeout off on the shared
        # session. Without it the reverse of 0039 adds its constraint with no bounded lock wait.
        # 0042 covers the same gap on the forward path; neither can cover both, because a migration
        # runs on opposite sides of 0041 in the two directions.
        migrations.RunSQL(
            sql=migrations.RunSQL.noop,
            reverse_sql=["RESET lock_timeout", "RESET statement_timeout"],
        ),
    ]
