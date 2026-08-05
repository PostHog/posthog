import django.db.models.manager
from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid, CreateIndexConcurrently, ValidateConstraint


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY and ADD CONSTRAINT ... NOT VALID / VALIDATE can't share a transaction.
    atomic = False

    dependencies = [
        ("replay_vision", "0058_delete_replayquotagrant"),
    ]

    operations = [
        # State-only: `objects` becomes configured-only and `all_origins` is the unfiltered escape
        # hatch, with `base_manager_name` keeping FK traversal and cascades unfiltered.
        migrations.AlterModelOptions(
            name="replayscanner",
            options={"base_manager_name": "all_origins"},
        ),
        migrations.AlterModelManagers(
            name="replayscanner",
            managers=[
                ("objects", django.db.models.manager.Manager()),
                ("all_origins", django.db.models.manager.Manager()),
            ],
        ),
        # Both carry db_default, so these are metadata-only ADD COLUMNs with no table rewrite and no
        # follow-up DROP DEFAULT. Every existing row is a configured scanner with no inline key.
        migrations.AddField(
            model_name="replayscanner",
            name="origin",
            field=models.CharField(
                choices=[("configured", "Configured"), ("inline", "Inline")],
                db_default="configured",
                default="configured",
                help_text="Whether a user saved this scanner or an inline scan minted it. See `ScannerOrigin`.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="replayscanner",
            name="inline_key",
            field=models.CharField(
                blank=True,
                db_default="",
                default="",
                help_text="Config fingerprint an inline scan resolves by. Empty for configured scanners.",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="replayscanner",
            name="name",
            field=models.CharField(
                blank=True,
                help_text="Human-readable name, unique within the team. Empty for inline scanners, which aren't named.",
                max_length=255,
            ),
        ),
        # A conditional UniqueConstraint is a partial unique index in Postgres, which has no NOT VALID
        # form — so build the index concurrently (lock-free) and record the constraint state-only, the
        # same shape as 0030. Django's RemoveConstraint emits DROP INDEX for a conditional constraint,
        # so state and database agree about what this object is.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="replayscanner",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("origin", "configured")),
                        fields=("team", "name"),
                        name="replay_scanner_unique_configured_team_name",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="replay_scanner_unique_configured_team_name",
                    table_name="replay_vision_replayscanner",
                    columns='("team_id", "name")',
                    unique=True,
                    where="WHERE \"origin\" = 'configured'",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="replayscanner",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("origin", "inline")),
                        fields=("team", "inline_key"),
                        name="replay_scanner_unique_team_inline_key",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="replay_scanner_unique_team_inline_key",
                    table_name="replay_vision_replayscanner",
                    columns='("team_id", "inline_key")',
                    unique=True,
                    where="WHERE \"origin\" = 'inline'",
                ),
            ],
        ),
        # Replaced by the partial index above. Dropped only once its replacement exists, so team name
        # uniqueness is never unenforced.
        migrations.RemoveConstraint(
            model_name="replayscanner",
            name="replay_scanner_unique_team_name",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="replayscanner",
                    index=models.Index(
                        condition=models.Q(("origin", "inline")),
                        fields=["created_at"],
                        name="rl_inline_created_idx",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="rl_inline_created_idx",
                    table_name="replay_vision_replayscanner",
                    columns='("created_at")',
                    where="WHERE \"origin\" = 'inline'",
                ),
            ],
        ),
        # Every existing row already satisfies this, but NOT VALID keeps the ADD off the full-table scan.
        AddConstraintNotValid(
            model_name="replayscanner",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("inline_key", ""), ("origin", "configured"))
                    | (models.Q(("origin", "inline")) & ~models.Q(("inline_key", "")))
                ),
                name="replay_scanner_inline_key_matches_origin",
            ),
        ),
        ValidateConstraint(
            model_name="replayscanner",
            name="replay_scanner_inline_key_matches_origin",
        ),
    ]
