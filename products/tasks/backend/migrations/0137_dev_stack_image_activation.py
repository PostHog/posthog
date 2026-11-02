import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0136_alter_loop_client_provenance_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DevStackImageTarget",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("region", models.CharField(max_length=16)),
                ("name", models.CharField(max_length=128)),
                ("enabled", models.BooleanField(default=False)),
                ("auto_refresh", models.BooleanField(default=True)),
                ("observation_revision", models.PositiveBigIntegerField(default=0)),
                ("generation", models.PositiveBigIntegerField(default=0)),
                ("base_reference", models.TextField(default="")),
                ("repository_sha", models.CharField(default="", max_length=40)),
                ("recipe_sha", models.CharField(default="", max_length=64)),
                ("request_key", models.CharField(default="", max_length=128)),
                ("pending_request_key", models.CharField(default="", max_length=128)),
                ("requested_at", models.DateTimeField(null=True)),
                ("observed_at", models.DateTimeField(null=True)),
                ("observation_error", models.CharField(default="", max_length=256)),
                ("active_image_id", models.CharField(default="", max_length=128)),
                ("active_agent_version", models.CharField(default="", max_length=64)),
                ("active_generation", models.PositiveBigIntegerField(default=0)),
                ("active_base_reference", models.TextField(default="")),
                ("active_repository_sha", models.CharField(default="", max_length=40)),
                ("active_recipe_sha", models.CharField(default="", max_length=64)),
                ("activated_at", models.DateTimeField(null=True)),
                ("attempt_id", models.UUIDField(null=True)),
                ("next_retry_at", models.DateTimeField(null=True)),
                ("blocked_reason", models.CharField(default="", max_length=256)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("region", "name"), name="tasks_dev_stack_region_name")],
            },
        ),
        migrations.CreateModel(
            name="DevStackImageAttempt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("generation", models.PositiveBigIntegerField()),
                ("base_reference", models.TextField()),
                ("repository_sha", models.CharField(max_length=40)),
                ("recipe_sha", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("building", "Building"),
                            ("verifying", "Verifying"),
                            ("active", "Active"),
                            ("failed", "Failed"),
                            ("superseded", "Superseded"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(null=True)),
                ("bake_started_at", models.DateTimeField(null=True)),
                ("finished_at", models.DateTimeField(null=True)),
                ("lease_expires_at", models.DateTimeField(null=True)),
                ("deadline_at", models.DateTimeField(null=True)),
                ("owner", models.UUIDField(null=True)),
                ("candidate_image_id", models.CharField(default="", max_length=128)),
                ("verified_at", models.DateTimeField(null=True)),
                ("workflow_run_id", models.CharField(default="", max_length=128)),
                ("error", models.CharField(default="", max_length=256)),
                (
                    "target",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attempts",
                        to="tasks.devstackimagetarget",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["target", "bake_started_at"], name="tasks_dev_stack_started")],
            },
        ),
    ]
