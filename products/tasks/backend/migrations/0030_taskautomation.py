import uuid

import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1066_alter_insight_saved"),
        ("tasks", "0029_task_ci_prompt"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskAutomation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("cron_expression", models.CharField(max_length=100)),
                ("timezone", models.CharField(default="UTC", max_length=128)),
                ("template_id", models.CharField(blank=True, max_length=255, null=True)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "task",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="automation",
                        to="tasks.task",
                    ),
                ),
                ("last_error", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "last_task_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="tasks.taskrun",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_automation",
                "ordering": ["task__title", "-created_at"],
            },
        ),
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
                    ("support_queue", "Support Queue"),
                    ("session_summaries", "Session Summaries"),
                    ("signal_report", "Signal Report"),
                ],
                max_length=20,
            ),
        ),
    ]
