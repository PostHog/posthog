# Initial migration for social_signals product.
#
# Hand-written rather than generated — the dev environment for this branch
# can't run `makemigrations`. Re-run `python manage.py makemigrations
# social_signals --check` after installing the env to confirm parity.

import uuid

import django.db.models.deletion
from django.db import migrations, models

import products.social_signals.backend.models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MentionSource",
            fields=[
                ("team_id", models.BigIntegerField(db_index=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("octolens", "octolens"), ("manual", "manual")],
                        max_length=64,
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                (
                    "ingest_token",
                    models.CharField(
                        db_index=True,
                        default=products.social_signals.backend.models._generate_ingest_token,
                        max_length=64,
                        unique=True,
                    ),
                ),
                ("config", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "default_manager_name": "all_teams",
            },
        ),
        migrations.CreateModel(
            name="Mention",
            fields=[
                ("team_id", models.BigIntegerField(db_index=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "platform",
                    models.CharField(
                        choices=[
                            ("x", "x"),
                            ("linkedin", "linkedin"),
                            ("reddit", "reddit"),
                            ("hacker_news", "hacker_news"),
                            ("github", "github"),
                            ("youtube", "youtube"),
                            ("bluesky", "bluesky"),
                            ("mastodon", "mastodon"),
                            ("other", "other"),
                        ],
                        default="other",
                        max_length=32,
                    ),
                ),
                (
                    "mention_type",
                    models.CharField(
                        choices=[
                            ("post", "post"),
                            ("comment", "comment"),
                            ("reply", "reply"),
                            ("article", "article"),
                            ("issue", "issue"),
                            ("other", "other"),
                        ],
                        default="post",
                        max_length=32,
                    ),
                ),
                ("external_id", models.CharField(max_length=512)),
                ("url", models.URLField(blank=True, max_length=2048)),
                ("content", models.TextField(blank=True)),
                ("language", models.CharField(blank=True, max_length=16)),
                ("author_handle", models.CharField(blank=True, max_length=255)),
                ("author_display_name", models.CharField(blank=True, max_length=255)),
                ("author_profile_url", models.URLField(blank=True, max_length=2048)),
                ("author_followers", models.IntegerField(blank=True, null=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("captured_at", models.DateTimeField(auto_now_add=True)),
                ("engagement", models.JSONField(blank=True, default=dict)),
                ("raw_payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("analyzing", "analyzing"),
                            ("done", "done"),
                            ("failed", "failed"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("last_error", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentions",
                        to="social_signals.mentionsource",
                    ),
                ),
            ],
            options={
                "ordering": ["-captured_at"],
                "default_manager_name": "all_teams",
            },
        ),
        migrations.CreateModel(
            name="MentionAnalysis",
            fields=[
                ("team_id", models.BigIntegerField(db_index=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("classify_and_sentiment", "classify_and_sentiment")],
                        max_length=64,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("succeeded", "succeeded"),
                            ("failed", "failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("result", models.JSONField(blank=True, default=dict)),
                ("model_used", models.CharField(blank=True, max_length=128)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "mention",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analyses",
                        to="social_signals.mention",
                    ),
                ),
            ],
            options={
                "default_manager_name": "all_teams",
            },
        ),
        migrations.AddConstraint(
            model_name="mentionsource",
            constraint=models.UniqueConstraint(
                fields=("team_id", "kind"),
                name="ss_unique_source_per_team_kind",
            ),
        ),
        migrations.AddConstraint(
            model_name="mention",
            constraint=models.UniqueConstraint(
                fields=("team_id", "source", "external_id"),
                name="ss_unique_mention_per_source",
            ),
        ),
        migrations.AddIndex(
            model_name="mention",
            index=models.Index(
                fields=["team_id", "platform", "-posted_at"],
                name="ss_mention_team_plat_posted",
            ),
        ),
        migrations.AddIndex(
            model_name="mention",
            index=models.Index(
                fields=["team_id", "-captured_at"],
                name="ss_mention_team_captured",
            ),
        ),
        migrations.AddIndex(
            model_name="mention",
            index=models.Index(
                fields=["team_id", "status"],
                name="ss_mention_team_status",
            ),
        ),
        migrations.AddConstraint(
            model_name="mentionanalysis",
            constraint=models.UniqueConstraint(
                fields=("mention", "kind"),
                name="ss_unique_analysis_per_mention_kind",
            ),
        ),
        migrations.AddIndex(
            model_name="mentionanalysis",
            index=models.Index(
                fields=["team_id", "kind", "-created_at"],
                name="ss_analysis_team_kind_recent",
            ),
        ),
    ]
