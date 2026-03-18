import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("metrics", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="spcmonitor",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="spcmonitor",
            name="archived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="spcmonitor",
            name="lifecycle_status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("awaiting_data", "Awaiting data"),
                    ("preview_ready", "Preview ready"),
                    ("active", "Active"),
                    ("paused", "Paused"),
                    ("archived", "Archived"),
                ],
                default="awaiting_data",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="spcmonitor",
            name="previous_lifecycle_state",
            field=models.CharField(
                blank=True,
                choices=[
                    ("awaiting_data", "Awaiting data"),
                    ("preview_ready", "Preview ready"),
                    ("active", "Active"),
                    ("paused", "Paused"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="spcmonitor",
            index=models.Index(fields=["team", "lifecycle_status"], name="metrics_spc_team_id_28ef9d_idx"),
        ),
        migrations.CreateModel(
            name="SeedJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                (
                    "scenario",
                    models.CharField(
                        choices=[
                            ("stable_baseline", "Stable baseline"),
                            ("sudden_spike", "Sudden spike"),
                            ("gradual_drift", "Gradual drift"),
                            ("sustained_degradation", "Sustained degradation"),
                            ("incident_and_recovery", "Incident and recovery"),
                        ],
                        max_length=64,
                    ),
                ),
                ("time_range", models.JSONField(default=dict)),
                (
                    "intensity",
                    models.CharField(
                        choices=[("subtle", "Subtle"), ("realistic", "Realistic"), ("dramatic", "Dramatic")],
                        max_length=16,
                    ),
                ),
                (
                    "direction",
                    models.CharField(blank=True, choices=[("up", "Up"), ("down", "Down")], max_length=8, null=True),
                ),
                ("recovery", models.BooleanField(default=True)),
                (
                    "seed_origin",
                    models.CharField(
                        choices=[("demo_prep", "Demo prep"), ("advanced_seed", "Advanced seed")],
                        default="demo_prep",
                        max_length=32,
                    ),
                ),
                ("seed_version", models.CharField(default="1.0", max_length=16)),
                ("event_strategy", models.CharField(blank=True, max_length=32, null=True)),
                ("event_names", models.JSONField(blank=True, default=list)),
                ("optional_filter_hints", models.JSONField(blank=True, default=dict)),
                ("advanced", models.JSONField(blank=True, default=dict)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("request_fingerprint_hash", models.CharField(max_length=64)),
                ("compatibility_snapshot", models.JSONField(blank=True, default=dict)),
                ("events_attempted", models.PositiveIntegerField(default=0)),
                ("events_written", models.PositiveIntegerField(default=0)),
                (
                    "failure_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("write_partial", "Write partial"),
                            ("write_interrupted", "Write interrupted"),
                        ],
                        max_length=32,
                        null=True,
                    ),
                ),
                ("error_message", models.TextField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "monitor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="metrics.spcmonitor",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["team", "created_at"], name="metrics_see_team_id_a20489_idx"),
                    models.Index(fields=["team", "status"], name="metrics_see_team_id_67270a_idx"),
                    models.Index(fields=["team", "request_fingerprint_hash"], name="metrics_see_team_id_e6f27f_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team", "idempotency_key"), name="metrics_seed_job_team_idempotency_uniq"
                    )
                ],
            },
        ),
    ]
