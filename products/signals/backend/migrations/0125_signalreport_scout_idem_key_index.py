from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Required by CreateIndexConcurrently, and why the column it indexes is added in 0124 instead.
    atomic = False

    dependencies = [
        ("signals", "0124_signalreport_scout_idempotency_key"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                CreateIndexConcurrently(
                    index_name="signals_report_scout_idem_key",
                    table_name="signals_signalreport",
                    columns="(team_id, scout_idempotency_key)",
                    unique=True,
                    where="WHERE scout_idempotency_key IS NOT NULL",
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="signalreport",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(scout_idempotency_key__isnull=False),
                        fields=("team", "scout_idempotency_key"),
                        name="signals_report_scout_idem_key",
                    ),
                ),
            ],
        ),
    ]
