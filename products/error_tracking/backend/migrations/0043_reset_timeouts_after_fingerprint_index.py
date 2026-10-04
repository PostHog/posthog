from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("error_tracking", "0042_restore_lean_fingerprint_index")]

    operations = [
        # 0042 sets lock_timeout and statement_timeout to 0 for its concurrent index builds.
        # Django applies migrations on one session, so those values stay off for every later
        # migration in the same run unless one puts them back. Restore the bounded lock wait
        # the deploy configures. This lives in its own migration because a CONCURRENTLY
        # operation and regular DDL must not share one file.
        migrations.RunSQL(
            sql=["RESET lock_timeout", "RESET statement_timeout"],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
