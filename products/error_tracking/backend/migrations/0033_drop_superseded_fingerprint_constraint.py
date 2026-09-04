from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0032_fingerprint_covering_index"),
    ]

    operations = [
        # 0032 turns off lock_timeout and statement_timeout for its concurrent build. Django applies
        # both migrations on one session, so those values stay off unless a migration puts them back.
        # Restore them to keep the bounded lock wait the deploy configures, because the drop below
        # queues every later read and write on the table while it waits for its ACCESS EXCLUSIVE lock.
        migrations.RunSQL(
            sql=["RESET lock_timeout", "RESET statement_timeout"],
            reverse_sql=migrations.RunSQL.noop,
        ),
        # `unique_fingerprint_for_team_covering` from 0032 enforces the same uniqueness, so keeping
        # this constraint only costs a second index write on every fingerprint insert. The drop takes
        # a brief ACCESS EXCLUSIVE lock; apply 0032 on its own first if the deploy must stage them.
        migrations.RemoveConstraint(
            model_name="errortrackingissuefingerprintv2",
            name="unique_fingerprint_for_team",
        ),
    ]
