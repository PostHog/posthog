import uuid

import django.db.models.manager
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0014_run_search_trgm"),
    ]

    operations = [
        migrations.CreateModel(
            name="StoryThresholdOverride",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("run_type", models.CharField(max_length=64)),
                ("story_stem", models.CharField(max_length=512)),
                ("pixel_threshold_percent", models.FloatField(blank=True, null=True)),
                ("ssim_dissimilarity_threshold", models.FloatField(blank=True, null=True)),
                ("created_by_id", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="story_threshold_overrides",
                        to="visual_review.repo",
                    ),
                ),
            ],
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name="storythresholdoverride",
            index=models.Index(fields=["repo", "run_type", "story_stem"], name="story_override_lookup"),
        ),
        migrations.AddConstraint(
            model_name="storythresholdoverride",
            constraint=models.UniqueConstraint(
                fields=["repo", "run_type", "story_stem"], name="unique_story_threshold_override"
            ),
        ),
    ]
