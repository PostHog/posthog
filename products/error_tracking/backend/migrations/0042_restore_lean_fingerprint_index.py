from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("error_tracking", "0041_errortrackingalertdestination_consecutive_failures_and_more"),
    ]

    operations = [
        # The lean index is created before the covering one is dropped, so a unique index on
        # (team_id, fingerprint) always exists. The ingestion insert names those columns as its
        # ON CONFLICT arbiter and fails without one.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="errortrackingissuefingerprintv2",
                    name="unique_fingerprint_for_team_covering",
                ),
                migrations.AddConstraint(
                    model_name="errortrackingissuefingerprintv2",
                    constraint=models.UniqueConstraint(
                        fields=["team", "fingerprint"],
                        name="unique_fingerprint_for_team",
                    ),
                ),
            ],
            database_operations=[
                # Django builds a constraint index with a plain CREATE UNIQUE INDEX, which locks
                # out writes for the whole build, so the database side runs CONCURRENTLY instead.
                CreateIndexConcurrently(
                    index_name="unique_fingerprint_for_team",
                    table_name="posthog_errortrackingissuefingerprintv2",
                    columns="(team_id, fingerprint)",
                    unique=True,
                ),
                DropIndexConcurrently(
                    index_name="unique_fingerprint_for_team_covering",
                    table_name="posthog_errortrackingissuefingerprintv2",
                    columns="(team_id, fingerprint) INCLUDE (id, issue_id, version)",
                    unique=True,
                ),
            ],
        ),
    ]
