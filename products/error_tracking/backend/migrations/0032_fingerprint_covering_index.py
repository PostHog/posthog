from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("error_tracking", "0031_errortrackingalert_errortrackingalertdestination_and_more"),
    ]

    operations = [
        # Django builds a constraint index with a plain CREATE UNIQUE INDEX, which locks out
        # writes for the whole build, so the database side runs CONCURRENTLY instead.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="errortrackingissuefingerprintv2",
                    constraint=models.UniqueConstraint(
                        fields=["team", "fingerprint"],
                        include=["id", "issue", "version"],
                        name="unique_fingerprint_for_team_covering",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_fingerprint_for_team_covering",
                    table_name="posthog_errortrackingissuefingerprintv2",
                    columns="(team_id, fingerprint) INCLUDE (id, issue_id, version)",
                    unique=True,
                ),
            ],
        ),
    ]
