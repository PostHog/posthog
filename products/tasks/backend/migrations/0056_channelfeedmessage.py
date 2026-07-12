import uuid

import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1231_duckgresserverteam"),
        ("tasks", "0055_task_artifact_registry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelFeedMessage",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                (
                    "author_kind",
                    models.CharField(
                        choices=[("human", "Human"), ("system", "System"), ("agent", "Agent")],
                        default="system",
                        max_length=16,
                    ),
                ),
                ("event", models.CharField(max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("content", models.TextField(blank=True, default="")),
                ("deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "author",
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
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feed_messages",
                        to="tasks.channel",
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
                "db_table": "posthog_task_channel_feed_message",
            },
        ),
        migrations.AddIndex(
            model_name="channelfeedmessage",
            index=models.Index(fields=["channel", "created_at"], name="task_channel_feed_msg_created"),
        ),
    ]
