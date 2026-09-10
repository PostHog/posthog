import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [("tasks", "0072_loop_skill_bundles")]
    operations = [
        migrations.CreateModel(
            name="TaskActivity",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("mention", "Mention"),
                            ("message", "Message"),
                            ("awaiting_input", "Awaiting input"),
                            ("completed", "Completed"),
                        ],
                        max_length=32,
                    ),
                ),
                ("activity_at", models.DateTimeField()),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                (
                    "message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activity_rows",
                        to="tasks.taskthreadmessage",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tasks.task"),
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
                (
                    "user",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.user",
                    ),
                ),
            ],
            options={"db_table": "posthog_task_activity"},
        ),
        migrations.AddConstraint(
            model_name="taskactivity",
            constraint=models.UniqueConstraint(fields=("team", "user", "task"), name="task_activity_user_task_unique"),
        ),
        migrations.AddIndex(
            model_name="taskactivity",
            index=models.Index(fields=["team", "user", "activity_at", "id"], name="task_activity_feed_idx"),
        ),
        migrations.AddIndex(
            model_name="taskactivity",
            index=models.Index(
                fields=["team", "user"],
                condition=models.Q(read_at__isnull=True),
                name="task_activity_unread_idx",
            ),
        ),
    ]
