import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("posthog", "1454_cimd_provisioning_review_status_length"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Topic",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("mission", models.TextField()),
                ("scout_digest", models.CharField(max_length=64, null=True)),
                ("chat_model", models.CharField(blank=True, max_length=255)),
                ("state", models.JSONField(default=dict)),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("archived", models.BooleanField(default=False)),
                ("deleted", models.BooleanField(default=False)),
                ("conversation_id", models.UUIDField(null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
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
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceView",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("state", models.JSONField(default=dict)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
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
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="ViewJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("turn_id", models.UUIDField(unique=True)),
                ("session", models.UUIDField()),
                ("task_id", models.UUIDField()),
                ("run_id", models.UUIDField(unique=True)),
                ("generation", models.PositiveBigIntegerField()),
                ("finished", models.BooleanField(default=False)),
                (
                    "view",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jobs",
                        to="meep.workspaceview",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="FileRevision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("path", models.TextField()),
                ("revision", models.PositiveBigIntegerField()),
                ("operation", models.UUIDField()),
                ("base", models.PositiveBigIntegerField(null=True)),
                ("competing_with", models.PositiveBigIntegerField(null=True)),
                ("contents", models.BinaryField()),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="files",
                        to="meep.topic",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("topic", "path", "revision"),
                        name="meep_unique_file_revision",
                    ),
                    models.UniqueConstraint(
                        fields=("topic", "path", "operation"),
                        name="meep_unique_file_operation",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DeletionReceipt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("replica", models.UUIDField()),
                ("revision", models.PositiveBigIntegerField()),
                (
                    "topic",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="meep.topic"),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("topic", "replica"), name="meep_unique_deletion_receipt")
                ],
            },
        ),
        migrations.CreateModel(
            name="CommandReceipt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("command_id", models.UUIDField()),
                ("revision", models.PositiveBigIntegerField()),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="receipts",
                        to="meep.topic",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("topic", "command_id"), name="meep_unique_topic_command")
                ],
            },
        ),
        migrations.CreateModel(
            name="ChatTurn",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("message_id", models.UUIDField()),
                ("text", models.TextField()),
                ("run_id", models.UUIDField(unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(null=True)),
                ("reply", models.TextField(blank=True)),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="turns",
                        to="meep.topic",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
                "constraints": [
                    models.UniqueConstraint(fields=("topic", "message_id"), name="meep_unique_topic_message")
                ],
            },
        ),
        migrations.CreateModel(
            name="BoardRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("item_id", models.UUIDField()),
                ("task_id", models.UUIDField()),
                ("run_id", models.UUIDField(unique=True)),
                ("finished", models.BooleanField(default=False)),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="board_runs",
                        to="meep.topic",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("finished", False)),
                        fields=("topic", "item_id"),
                        name="meep_one_live_board_run",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ViewReceipt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("command_id", models.UUIDField()),
                (
                    "view",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="meep.workspaceview",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("view", "command_id"), name="meep_unique_view_command")
                ],
            },
        ),
    ]
