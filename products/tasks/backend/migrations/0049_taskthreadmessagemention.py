import uuid

import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0048_task_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskThreadMessageMention",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "mentioned_user",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentions",
                        to="tasks.taskthreadmessage",
                    ),
                ),
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
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_thread_message_mention",
            },
        ),
        migrations.AddConstraint(
            model_name="taskthreadmessagemention",
            constraint=models.UniqueConstraint(
                fields=("message", "mentioned_user"), name="task_mention_message_user_unique"
            ),
        ),
        migrations.AddIndex(
            model_name="taskthreadmessagemention",
            index=models.Index(fields=["team", "mentioned_user", "created_at"], name="task_mention_team_user_created"),
        ),
    ]
