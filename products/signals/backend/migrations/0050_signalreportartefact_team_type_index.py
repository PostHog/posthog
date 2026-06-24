# Resolving the latest status artefact per report across a whole team in one pass —
# `WHERE team=? AND type=? ORDER BY report, created_at DESC` (DISTINCT ON). Backs the set-based
# join the inbox report-list sort uses instead of a per-row correlated subquery. atomic=False +
# SeparateDatabaseAndState because CONCURRENTLY cannot run in a transaction and bin/migrate
# re-runs a failed migration in full — non-idempotent ops must not share it.

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("signals", "0049_turn_on_scout_source_by_default"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="signalreportartefact",
                    index=models.Index(
                        fields=["team", "type", "report", "-created_at"], name="signals_sig_team_type_rpt_idx"
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="signals_sig_team_type_rpt_idx",
                    table_name="signals_signalreportartefact",
                    columns="(team_id, type, report_id, created_at DESC)",
                ),
            ],
        ),
    ]
