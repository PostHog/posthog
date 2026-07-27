# Renames the ReplayLens model + its fields to "Scanner" terminology.
# Phase 1 / feature-flagged: no production rows, so the brief
# deploy window where old pods reference the pre-rename schema is acceptable.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0005_alter_replaylens_model"),
    ]

    operations = [
        migrations.RenameModel(old_name="ReplayLens", new_name="ReplayScanner"),
        migrations.RenameField(model_name="replayscanner", old_name="lens_type", new_name="scanner_type"),
        migrations.RenameField(model_name="replayscanner", old_name="lens_config", new_name="scanner_config"),
        migrations.RenameField(model_name="replayscanner", old_name="lens_version", new_name="scanner_version"),
        migrations.RenameField(model_name="replayobservation", old_name="lens", new_name="scanner"),
        migrations.RenameField(model_name="replayobservation", old_name="lens_snapshot", new_name="scanner_snapshot"),
        migrations.RenameField(model_name="replayobservation", old_name="lens_result", new_name="scanner_result"),
        migrations.RemoveConstraint(model_name="replayscanner", name="replay_lens_unique_team_name"),
        migrations.AddConstraint(
            model_name="replayscanner",
            constraint=models.UniqueConstraint(fields=["team", "name"], name="replay_scanner_unique_team_name"),
        ),
        migrations.RemoveConstraint(model_name="replayscanner", name="replay_lens_sampling_rate_range"),
        migrations.AddConstraint(
            model_name="replayscanner",
            constraint=models.CheckConstraint(
                condition=models.Q(sampling_rate__gte=0.0) & models.Q(sampling_rate__lte=1.0),
                name="replay_scanner_sampling_rate_range",
            ),
        ),
        migrations.RemoveConstraint(model_name="replayobservation", name="replay_observation_unique_lens_session"),
        migrations.AddConstraint(
            model_name="replayobservation",
            constraint=models.UniqueConstraint(
                fields=["scanner", "session_id"], name="replay_observation_unique_scanner_session"
            ),
        ),
        # RenameIndex would re-rename the DB index but leave the in-state index pointing at the
        # now-renamed `lens` field; remove+add keeps state consistent with no drift.
        migrations.RemoveIndex(model_name="replayobservation", name="rlo_lens_status_idx"),
        migrations.AddIndex(
            model_name="replayobservation",
            index=models.Index(fields=["scanner", "status"], name="rlo_scanner_status_idx"),
        ),
        # Help-text-only state alignment for fields whose copy now reads "scanner" instead of "lens".
        # No SQL is emitted for these — they only refresh Django's migration state.
        migrations.AlterField(
            model_name="replayscanner",
            name="description",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Free-form description for the scanner management UI. Not used by the model.",
            ),
        ),
        migrations.AlterField(
            model_name="replayscanner",
            name="enabled",
            field=models.BooleanField(
                default=True,
                help_text="When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work.",
            ),
        ),
        migrations.AlterField(
            model_name="replayscanner",
            name="last_swept_at",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                help_text="Watermark for the scanner schedule's last fire; mirrors Temporal schedule state for recovery.",
            ),
        ),
        migrations.AlterField(
            model_name="replayobservation",
            name="session_id",
            field=models.CharField(
                help_text="Session recording id this scanner was applied to.",
                max_length=200,
            ),
        ),
        migrations.AlterField(
            model_name="replayobservation",
            name="triggered_by",
            field=models.CharField(
                choices=[("schedule", "Schedule"), ("on_demand", "On demand")],
                help_text="What started this observation: a per-scanner schedule fire or an explicit /observe/ call.",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="replayobservation",
            name="scanner_snapshot",
            field=models.JSONField(
                default=dict,
                help_text="Frozen view of the scanner at observation-create time; see `temporal.types.ScannerSnapshot`.",
            ),
        ),
        migrations.AlterField(
            model_name="replayobservation",
            name="scanner_result",
            field=models.JSONField(
                default=dict,
                help_text="Result data persisted on success (model output, signals count); see `temporal.types.ScannerResult`.",
            ),
        ),
    ]
