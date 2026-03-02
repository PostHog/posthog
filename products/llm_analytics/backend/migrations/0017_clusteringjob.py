import django.db.models.deletion
from django.db import migrations, models


def migrate_clustering_configs_to_jobs(apps, schema_editor):
    """Convert each existing ClusteringConfig into two ClusteringJob rows."""
    ClusteringConfig = apps.get_model("llm_analytics", "ClusteringConfig")
    ClusteringJob = apps.get_model("llm_analytics", "ClusteringJob")

    for config in ClusteringConfig.objects.all():
        for level, suffix in [("trace", "traces"), ("generation", "generations")]:
            ClusteringJob.objects.create(
                team_id=config.team_id,
                name=f"Default ({suffix})",
                analysis_level=level,
                event_filters=config.event_filters,
                enabled=True,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1002_experiment_exposure_preaggregation_enabled"),
        ("llm_analytics", "0016_alter_evaluation_evaluation_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClusteringJob",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
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
        migrations.RunPython(
            migrate_clustering_configs_to_jobs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
