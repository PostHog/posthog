import uuid

import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1166_oauth_impersonated_by"),
        ("tasks", "0044_alter_task_origin_product"),
    ]

    operations = [
        migrations.CreateModel(
            name="Channel",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(max_length=128)),
                (
                    "channel_type",
                    models.CharField(
                        choices=[("public", "Public"), ("personal", "Personal")],
                        default="public",
                        max_length=16,
                    ),
                ),
                ("deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
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
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_channel",
            },
        ),
        migrations.AddConstraint(
            model_name="channel",
            constraint=models.UniqueConstraint(
                condition=models.Q(("channel_type", "public"), ("deleted", False)),
                fields=("team", "name"),
                name="task_channel_team_name_public_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="channel",
            constraint=models.UniqueConstraint(
                condition=models.Q(("channel_type", "personal"), ("deleted", False)),
                fields=("team", "created_by"),
                name="task_channel_team_user_personal_unique",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="channel",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks",
                to="tasks.channel",
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["channel", "-created_at"], name="posthog_task_channel_feed_idx"),
        ),
        migrations.CreateModel(
            name="TaskThreadMessage",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("content", models.TextField()),
                ("forwarded_to_agent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "author",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "forwarded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "forwarded_run",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="tasks.taskrun",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="thread_messages",
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
            ],
            options={
                "db_table": "posthog_task_thread_message",
            },
        ),
        migrations.AddIndex(
            model_name="taskthreadmessage",
            index=models.Index(fields=["task", "created_at"], name="task_thread_msg_task_created"),
        ),
    ]
