import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1152_fix_device_bucketing_persist_across_auth"),
        ("githog", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GitHogPullRequestLayout",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("repository", models.CharField(max_length=255)),
                ("pr_number", models.IntegerField()),
                ("layout", models.JSONField(default=dict)),
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
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["team", "user", "repository", "pr_number"],
                        name="githog_gith_team_id_4aec24_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team", "user", "repository", "pr_number"),
                        name="unique_githog_pr_layout_per_user",
                    )
                ],
            },
        ),
    ]
