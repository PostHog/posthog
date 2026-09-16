from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("error_tracking", "0040_fingerprint_covering_index_first_seen")]

    operations = [
        # Both concurrent operations in 0040 turn off lock_timeout and statement_timeout, and Django
        # applies later migrations on one session, so those values stay off unless a migration puts
        # them back. Restore them to keep the bounded lock wait the deploy configures. This is its
        # own migration because the risk analyzer blocks regular DDL sharing a file with CONCURRENTLY.
        migrations.RunSQL(
            sql=["RESET lock_timeout", "RESET statement_timeout"],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
