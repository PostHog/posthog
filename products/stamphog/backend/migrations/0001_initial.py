import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("posthog", "1247_oauthaccesstoken_token_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="StamphogRepoConfig",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("repository", models.CharField(max_length=255)),
                ("enabled", models.BooleanField(default=True)),
                ("github_installation_id", models.CharField(max_length=64)),
                ("policy_overrides", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
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
            name="ReviewRun",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("pr_number", models.IntegerField()),
                ("pr_url", models.CharField(max_length=512)),
                ("head_sha", models.CharField(max_length=64)),
                ("delivery_id", models.CharField(max_length=64, null=True, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "queued"),
                            ("gated", "gated"),
                            ("reviewing", "reviewing"),
                            ("completed", "completed"),
                            ("failed", "failed"),
                            ("superseded", "superseded"),
                        ],
                        default="queued",
                        max_length=32,
                    ),
                ),
                (
                    "verdict",
                    models.CharField(
                        choices=[
                            ("none", "none"),
                            ("approved", "approved"),
                            ("refused", "refused"),
                            ("escalate", "escalate"),
                            ("wait", "wait"),
                            ("error", "error"),
                        ],
                        default="none",
                        max_length=32,
                    ),
                ),
                ("gate_result", models.JSONField(null=True)),
                ("output", models.JSONField(default=dict)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(null=True)),
                (
                    "repo_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review_runs",
                        to="stamphog.stamphogrepoconfig",
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
        migrations.AddConstraint(
            model_name="stamphogrepoconfig",
            constraint=models.UniqueConstraint(fields=("team", "repository"), name="unique_stamphog_repo_per_team"),
        ),
    ]
