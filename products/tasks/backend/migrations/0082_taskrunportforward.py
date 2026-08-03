import uuid

import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0081_channelcontextgeneration_channelinstructions_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskRunPortForward",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("port", models.PositiveIntegerField(help_text="Loopback port exposed from inside the task sandbox")),
                ("name", models.CharField(blank=True, default="", max_length=80)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("stopped", "Stopped"), ("expired", "Expired")],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("last_accessed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tasks.task"),
                ),
                (
                    "task_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="port_forwards",
                        to="tasks.taskrun",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="posthog.team"),
                ),
            ],
            options={
                "db_table": "posthog_task_run_port_forward",
                "indexes": [
                    models.Index(fields=["team", "task_run", "status"], name="task_run_pf_team_run_stat_idx"),
                    models.Index(fields=["expires_at"], name="task_run_pf_expires_at_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(status="active"),
                        fields=("task_run", "port"),
                        name="task_run_pf_active_port_unique",
                    )
                ],
            },
        ),
    ]
