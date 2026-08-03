from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("replay_vision", "0058_delete_replayquotagrant"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayscanner",
            name="ad_hoc_key",
            field=models.CharField(
                blank=True,
                db_default="",
                default="",
                help_text="Config fingerprint of a scanner minted implicitly by an ad-hoc scan. Empty for configured scanners.",
                max_length=64,
            ),
        ),
        # A conditional UniqueConstraint is a partial unique index in Postgres, which has no NOT VALID
        # form — so build the index concurrently (lock-free) and record the constraint state-only. The
        # helper is idempotent under bin/migrate retries.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="replayscanner",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("ad_hoc_key", ""), _negated=True),
                        fields=("team", "ad_hoc_key"),
                        name="replay_scanner_unique_team_ad_hoc_key",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="replay_scanner_unique_team_ad_hoc_key",
                    table_name="replay_vision_replayscanner",
                    columns='("team_id", "ad_hoc_key")',
                    unique=True,
                    where="WHERE \"ad_hoc_key\" != ''",
                ),
            ],
        ),
    ]
