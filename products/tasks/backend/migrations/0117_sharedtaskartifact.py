import django.utils.timezone
import django.db.models.manager
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0116_drop_task_session_storage_key_like_index"),
        ("posthog", "1333_uploaded_media_library_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedTaskArtifact",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("artifact_id", models.CharField(max_length=128)),
                ("name", models.CharField(max_length=512)),
                ("content_type", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
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
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shared_artifacts",
                        to="tasks.taskrun",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shared_artifacts",
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
                "db_table": "posthog_task_shared_artifact",
                "default_manager_name": "all_teams",
                "constraints": [
                    models.UniqueConstraint(fields=("task", "name"), name="task_shared_artifact_task_name_unique"),
                ],
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
