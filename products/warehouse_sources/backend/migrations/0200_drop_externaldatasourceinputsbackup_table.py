from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0199_remove_externaldatasourceinputsbackup_state"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS warehouse_sources_externaldatasourceinputsbackup",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
