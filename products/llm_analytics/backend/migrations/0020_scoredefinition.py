import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1039_subscription_dashboard_export_insights"),
        ("llm_analytics", "0019_rename_default_clustering_jobs"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScoreDefinition",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, null=True, blank=True)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "kind",
                    models.CharField(
                        choices=[("categorical", "categorical"), ("numeric", "numeric"), ("boolean", "boolean")],
                        max_length=32,
                    ),
                ),
                ("archived", models.BooleanField(default=False)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "ordering": ["name", "id"],
            },
        ),
        migrations.CreateModel(
            name="ScoreDefinitionVersion",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                ("config", models.JSONField(default=dict)),
                (
                    "definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="llm_analytics.scoredefinition",
                    ),
                ),
            ],
            options={
                "ordering": ["-version"],
            },
        ),
        migrations.AddField(
            model_name="scoredefinition",
            name="current_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="llm_analytics.scoredefinitionversion",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoredefinitionversion",
            constraint=models.UniqueConstraint(
                fields=("definition", "version"),
                name="uniq_llma_score_def_ver",
            ),
        ),
        migrations.AddIndex(
            model_name="scoredefinition",
            index=models.Index(
                fields=["team", "kind", "archived"],
                name="llma_score_def_team_kind_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="scoredefinitionversion",
            index=models.Index(
                fields=["definition", "-version"],
                name="llma_score_def_ver_def_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="scoredefinitionversion",
            index=models.Index(fields=["created_at"], name="llma_score_def_ver_created_idx"),
        ),
    ]
