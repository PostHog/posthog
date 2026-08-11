import django.db.models.manager
from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    """Columns and state. Transactional: the concurrent index builds live in 0060 so this part keeps
    its rollback safety."""

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
        # `blank` is a validation flag, so this alteration emits no SQL.
        migrations.AlterField(
            model_name="replayscanner",
            name="name",
            field=models.CharField(
                blank=True,
                help_text="Human-readable name, unique within the team. Empty for inline scanners, which aren't named.",
                max_length=255,
            ),
        ),
        # Every row added above already satisfies this; NOT VALID keeps the ADD off a full-table scan
        # and 0061 validates it once the rest of the schema is in place.
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
    ]
