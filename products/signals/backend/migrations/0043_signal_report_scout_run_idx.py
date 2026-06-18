from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [('signals', '0042_signalreport_created_by_scout_run_and_more')]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="signalreport",
                    index=models.Index(fields=["created_by_scout_run"], name="signal_report_scout_run_idx"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="signal_report_scout_run_idx",
                    table_name="signals_signalreport",
                    columns="(created_by_scout_run_id)",
                ),
            ],
        ),
    ]
