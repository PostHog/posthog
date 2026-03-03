import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1002_experiment_exposure_preaggregation_enabled"),
        ("llm_analytics", "0016_alter_evaluation_evaluation_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClusteringJob",
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
                ("name", models.CharField(max_length=100)),
                (
                    "analysis_level",
                    models.CharField(
                        choices=[("trace", "trace"), ("generation", "generation")],
                        max_length=20,
                    ),
                ),
                ("event_filters", models.JSONField(blank=True, default=list)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="clustering_jobs",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "app_label": "llm_analytics",
            },
        ),
        migrations.AddConstraint(
            model_name="clusteringjob",
            constraint=models.UniqueConstraint(
                fields=("team", "name"),
                name="unique_clustering_job_name_per_team",
            ),
        ),
    ]
