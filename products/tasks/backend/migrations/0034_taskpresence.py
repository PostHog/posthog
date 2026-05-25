import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1166_oauth_impersonated_by"),
        ("tasks", "0033_task_archived_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskPresence",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="tasks.task",
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
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "push_token",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.userpushtoken",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_presence",
            },
        ),
        migrations.AddConstraint(
            model_name="taskpresence",
            constraint=models.UniqueConstraint(
                fields=("task", "push_token"),
                name="task_presence_task_push_token_unique",
            ),
        ),
    ]
