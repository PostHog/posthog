from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0103_remove_signalreportcanvasgeneration_report_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS signals_signalreportcanvasgeneration;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS signals_signalreportcanvas;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
