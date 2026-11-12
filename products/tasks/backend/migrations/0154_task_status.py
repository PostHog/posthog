import django.utils.timezone
import django.db.models.deletion
import django.contrib.postgres.fields
from django.db import migrations, models

import posthog.models.utils

STATUS_CHOICES = [("queued", "Queued"), ("running", "Running"), ("idle", "Idle"), ("done", "Done")]
REASON_CHOICES = [
    ("turn_closed", "Turn closed"),
    ("user_stopped", "User stopped"),
    ("provision_failed", "Provision failed"),
    ("unexpected_failure", "Unexpected failure"),
    ("timed_out", "Timed out"),
    ("budget_spent", "Budget spent"),
    ("credit_spent", "Credit spent"),
    ("access_changed", "Access changed"),
    ("finished", "Finished"),
    ("closed", "Closed"),
    ("cancelled", "Cancelled"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0153_squash_2026_11_02_finalize_fks"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskStatusChange",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("run_id", models.UUIDField(blank=True, null=True)),
                ("status", models.CharField(choices=STATUS_CHOICES, max_length=16)),
                ("reason", models.CharField(blank=True, choices=REASON_CHOICES, max_length=32, null=True)),
                ("detail", models.TextField(blank=True, null=True)),
                ("changed_by", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "task",
                    models.ForeignKey(
                        db_constraint=False,
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="status_changes",
                        to="tasks.task",
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
                "db_table": "posthog_task_status_change",
                "indexes": [models.Index(fields=["task", "-created_at"], name="task_status_change_task_idx")],
            },
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="task",
                    name="status",
                    field=models.CharField(
                        blank=True, choices=STATUS_CHOICES, default="idle", max_length=16, null=True
                    ),
                ),
            ],
            database_operations=[
                migrations.AddField(
                    model_name="task",
                    name="status",
                    field=models.CharField(blank=True, choices=STATUS_CHOICES, max_length=16, null=True),
                ),
            ],
        ),
        migrations.AddField(
            model_name="task",
            name="status_reason",
            field=models.CharField(blank=True, choices=REASON_CHOICES, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="status_detail",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="status_changed_by",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="head_branch",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="pr_urls",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=512), blank=True, db_default=[], default=list
            ),
        ),
    ]
