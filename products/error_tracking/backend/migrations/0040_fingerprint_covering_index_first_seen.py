from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("error_tracking", "0039_drop_superseded_fingerprint_constraint"),
    ]

    operations = [
        # Cymbal's fingerprint lookup also reads first_seen, so without it in the index the
        # lookup pays a heap fetch per call. INCLUDE cannot be altered in place, so the index
        # is rebuilt under a new name and the old one dropped once the new one is live.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="errortrackingissuefingerprintv2",
                    constraint=models.UniqueConstraint(
                        fields=["team", "fingerprint"],
                        include=["id", "issue", "version", "first_seen"],
                        name="unique_fingerprint_for_team_covering_v2",
                    ),
                ),
                migrations.RemoveConstraint(
                    model_name="errortrackingissuefingerprintv2",
                    name="unique_fingerprint_for_team_covering",
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_fingerprint_for_team_covering_v2",
                    table_name="posthog_errortrackingissuefingerprintv2",
                    columns="(team_id, fingerprint) INCLUDE (id, issue_id, version, first_seen)",
                    unique=True,
                ),
                # 0038 created this as a plain unique index, not a table constraint, so it drops
                # concurrently and never takes ACCESS EXCLUSIVE on the table.
                DropIndexConcurrently(
                    index_name="unique_fingerprint_for_team_covering",
                    table_name="posthog_errortrackingissuefingerprintv2",
                    columns="(team_id, fingerprint) INCLUDE (id, issue_id, version)",
                    unique=True,
                ),
            ],
        ),
    ]
