import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("live_debugger", "0002_add_program"),
    ]

    operations = [
        migrations.CreateModel(
            name="LiveInvestigation",
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
                ("chain_depth", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("watching", "Watching"),
                            ("analyzing", "Analyzing"),
                            ("complete", "Complete"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="watching",
                        max_length=16,
                    ),
                ),
                ("workflow_id", models.CharField(max_length=255)),
                ("min_events", models.PositiveIntegerField()),
                ("max_duration_seconds", models.PositiveIntegerField()),
                ("signal_source_type", models.CharField(max_length=64)),
                ("signal_source_id", models.CharField(blank=True, default="", max_length=128)),
                ("brief", models.JSONField()),
                ("findings", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
                (
                    "program",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="investigations",
                        to="live_debugger.livedebuggerprogram",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="children",
                        to="live_debugger.liveinvestigation",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_liveinvestigation",
                "managed": True,
                "indexes": [
                    models.Index(fields=["status"], name="live_inv_status_idx"),
                    models.Index(fields=["team_id", "status"], name="live_inv_team_status_idx"),
                    models.Index(fields=["program_id"], name="live_inv_program_idx"),
                ],
            },
        ),
    ]
