from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.functions import Upper


class Migration(migrations.Migration):
    dependencies = [("signals", "0225_anomalyscoringdueinsight")]

    # ALTER INDEX changes the storage parameter in place, so the indexes are not rebuilt.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        # fastupdate takes ACCESS EXCLUSIVE on the index, and queries that plan against
                        # the table queue behind a waiting request. Fail fast and let bin/migrate retry.
                        "SET LOCAL lock_timeout = '5s'",
                        'ALTER INDEX IF EXISTS "signals_report_title_trgm" SET (fastupdate = off)',
                        'ALTER INDEX IF EXISTS "signals_report_summary_trgm" SET (fastupdate = off)',
                    ],
                    reverse_sql=[
                        "SET LOCAL lock_timeout = '5s'",
                        'ALTER INDEX IF EXISTS "signals_report_title_trgm" SET (fastupdate = on)',
                        'ALTER INDEX IF EXISTS "signals_report_summary_trgm" SET (fastupdate = on)',
                    ],
                ),
            ],
            state_operations=[
                migrations.RemoveIndex(model_name="signalreport", name="signals_report_title_trgm"),
                migrations.RemoveIndex(model_name="signalreport", name="signals_report_summary_trgm"),
                migrations.AddIndex(
                    model_name="signalreport",
                    index=GinIndex(
                        OpClass(Upper("title"), name="gin_trgm_ops"),
                        name="signals_report_title_trgm",
                        fastupdate=False,
                    ),
                ),
                migrations.AddIndex(
                    model_name="signalreport",
                    index=GinIndex(
                        OpClass(Upper("summary"), name="gin_trgm_ops"),
                        name="signals_report_summary_trgm",
                        fastupdate=False,
                    ),
                ),
            ],
        ),
    ]
