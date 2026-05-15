import uuid

import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0031_task_github_user_integration"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="task",
                    name="origin_product",
                    field=models.CharField(
                        choices=[
                            ("error_tracking", "Error Tracking"),
                            ("eval_clusters", "Eval Clusters"),
                            ("user_created", "User Created"),
                            ("automation", "Automation"),
                            ("slack", "Slack"),
                            ("sendblue", "Sendblue"),
                            ("support_queue", "Support Queue"),
                            ("session_summaries", "Session Summaries"),
                            ("signal_report", "Signal Report"),
                        ],
                        max_length=20,
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.CreateModel(
            name="TaskPrewarmedSandbox",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("pool_key", models.CharField(db_index=True, max_length=255)),
                (
                    "origin_product",
                    models.CharField(
                        choices=[
                            ("error_tracking", "Error Tracking"),
                            ("eval_clusters", "Eval Clusters"),
                            ("user_created", "User Created"),
                            ("automation", "Automation"),
                            ("slack", "Slack"),
                            ("sendblue", "Sendblue"),
                            ("support_queue", "Support Queue"),
                            ("session_summaries", "Session Summaries"),
                            ("signal_report", "Signal Report"),
                        ],
                        max_length=20,
                    ),
                ),
                ("repository", models.CharField(max_length=255)),
                ("provider", models.CharField(max_length=32)),
                ("template", models.CharField(max_length=50)),
                ("sandbox_id", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("provisioning", "Provisioning"),
                            ("available", "Available"),
                            ("leased", "Leased"),
                            ("terminated", "Terminated"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="provisioning",
                        max_length=20,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("last_error", models.TextField(blank=True, null=True)),
                ("warmed_at", models.DateTimeField(blank=True, null=True)),
                ("leased_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "leased_task_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="prewarmed_sandbox_leases",
                        to="tasks.taskrun",
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "db_table": "posthog_task_prewarmed_sandbox",
                "indexes": [
                    models.Index(fields=["team", "pool_key", "status"], name="task_prewarmed_team_pool_idx"),
                    models.Index(fields=["pool_key", "status"], name="task_prewarmed_pool_status_idx"),
                    models.Index(
                        fields=["team", "origin_product", "repository", "status"],
                        name="task_prewarmed_team_origin_idx",
                    ),
                    models.Index(
                        fields=["origin_product", "repository", "status"], name="task_prewarmed_origin_repo_idx"
                    ),
                ],
            },
        ),
    ]
