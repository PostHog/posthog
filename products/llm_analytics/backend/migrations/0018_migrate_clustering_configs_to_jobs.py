from django.db import migrations


def migrate_clustering_configs_to_jobs(apps, schema_editor):
    """Convert each existing ClusteringConfig into two ClusteringJob rows."""
    ClusteringConfig = apps.get_model("llm_analytics", "ClusteringConfig")
    ClusteringJob = apps.get_model("llm_analytics", "ClusteringJob")

    for config in ClusteringConfig.objects.all():
        for level, suffix in [("trace", "traces"), ("generation", "generations")]:
            ClusteringJob.objects.create(
                team_id=config.team_id,
                name=f"Default - {suffix}",
                analysis_level=level,
                event_filters=config.event_filters,
                enabled=True,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0017_clusteringjob"),
    ]

    operations = [
        migrations.RunPython(
            migrate_clustering_configs_to_jobs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
