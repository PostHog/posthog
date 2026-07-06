# Latest-wins lookups: artefacts are append-only, so deriving a report's current status / log
# tail is `WHERE report=? AND type=? ORDER BY created_at DESC` — this index makes it a seek.
# Kept separate from 0047 (and atomic=False) because CONCURRENTLY cannot run in a transaction,
# and bin/migrate re-runs a failed migration in full — non-idempotent ops must not share it.

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("signals", "0047_signalreportartefact_updated_at_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="signalreportartefact",
                    index=models.Index(fields=["report", "type", "-created_at"], name="signals_sig_rpt_type_ct_idx"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="signals_sig_rpt_type_ct_idx",
                    table_name="signals_signalreportartefact",
                    columns="(report_id, type, created_at DESC)",
                ),
            ],
        ),
    ]
