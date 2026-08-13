import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1231_duckgresserverteam"),
        ("tasks", "0069_remove_code_home_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="SandboxSession",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "sandbox_id",
                    models.CharField(
                        help_text="Provider sandbox id (e.g. Modal object id)", max_length=255, unique=True
                    ),
                ),
                (
                    "origin_product",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("onboarding", "Onboarding"),
                            ("error_tracking", "Error Tracking"),
                            ("eval_clusters", "Eval Clusters"),
                            ("user_created", "User Created"),
                            ("automation", "Automation"),
                            ("slack", "Slack"),
                            ("support_queue", "Support Queue"),
                            ("session_summaries", "Session Summaries"),
                            ("posthog_ai", "PostHog AI"),
                            ("experiments", "Experiments"),
                            ("signal_report", "Signal Report"),
                            ("signals_scout", "Signals Scout"),
                            ("support_reply", "Support Reply"),
                            ("hogdesk", "HogDesk"),
                            ("review_hog", "ReviewHog"),
                            ("image_builder", "Image Builder"),
                            ("loop", "Loop"),
                        ],
                        help_text="Task origin at provision time, denormalized for per-origin aggregation",
                        max_length=20,
                        null=True,
                    ),
                ),
                (
                    "prewarmed",
                    models.BooleanField(default=False, help_text="Sandbox was provisioned ahead of any user demand"),
                ),
                (
                    "vm_runtime",
                    models.BooleanField(
                        default=False, help_text="Modal VM runtime rather than gVisor (billed differently)"
                    ),
                ),
                ("cpu_cores", models.FloatField(help_text="CPU core limit")),
                ("memory_gb", models.FloatField(help_text="Memory limit in GiB")),
                ("ttl_seconds", models.IntegerField(help_text="Hard TTL after which the provider kills the sandbox")),
                ("burstable", models.BooleanField(default=False)),
                (
                    "cpu_request_cores",
                    models.FloatField(blank=True, help_text="Reserved CPU floor when burstable", null=True),
                ),
                (
                    "memory_request_mb",
                    models.IntegerField(blank=True, help_text="Reserved memory floor when burstable", null=True),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, help_text="Sandbox provisioned"),
                ),
                (
                    "ttl_expires_at",
                    models.DateTimeField(help_text="Absolute provider kill deadline (creation boundary + TTL)"),
                ),
                (
                    "user_attributed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Start of the user-attributable window; NULL while (pre)warm and unclaimed",
                        null=True,
                    ),
                ),
                (
                    "last_user_activity_at",
                    models.DateTimeField(
                        blank=True, help_text="Most recent user message routed to this sandbox's run", null=True
                    ),
                ),
                (
                    "ended_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Sandbox destroyed; NULL rows are clamped to ttl_expires_at",
                        null=True,
                    ),
                ),
                (
                    "ended_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("cleanup", "Cleanup"),
                            ("reaped", "Reaped"),
                        ],
                        max_length=20,
                        null=True,
                    ),
                ),
                (
                    "task_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="sandbox_sessions", to="tasks.taskrun"
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_sandbox_session",
                "indexes": [
                    models.Index(fields=["ended_at"], name="sandbox_session_ended_at_idx"),
                    models.Index(
                        condition=models.Q(("ended_at__isnull", True)),
                        fields=["ttl_expires_at"],
                        name="sandbox_session_open_ttl_idx",
                    ),
                    models.Index(fields=["team", "user_attributed_at"], name="sandbox_session_team_attr_idx"),
                ],
            },
        ),
    ]
