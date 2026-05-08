import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1090_batchexportrun_records_failed"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("llm_analytics", "0025_evaluation_reports"),
    ]

    operations = [
        migrations.CreateModel(
            name="LLMSkill",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=64)),
                ("description", models.CharField(max_length=1024)),
                ("body", models.TextField()),
                ("license", models.CharField(blank=True, default="", max_length=255)),
                ("compatibility", models.CharField(blank=True, default="", max_length=500)),
                ("allowed_tools", models.JSONField(blank=True, default=list)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("version", models.PositiveIntegerField(default=1)),
                ("is_latest", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted", models.BooleanField(default=False)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="llmskill",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False)),
                fields=("team", "name", "version"),
                name="unique_llm_skill_version_per_team",
            ),
        ),
        migrations.AddConstraint(
            model_name="llmskill",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False), ("is_latest", True)),
                fields=("team", "name"),
                name="unique_llm_skill_latest_per_team",
            ),
        ),
        migrations.CreateModel(
            name="LLMSkillFile",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("path", models.CharField(max_length=500)),
                ("content", models.TextField()),
                ("content_type", models.CharField(default="text/plain", max_length=100)),
                (
                    "skill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="files",
                        to="llm_analytics.llmskill",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="llmskillfile",
            constraint=models.UniqueConstraint(
                fields=("skill", "path"),
                name="unique_skill_file_path",
            ),
        ),
    ]
