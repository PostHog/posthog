from django.db import migrations


def rename_default_clustering_jobs(apps, schema_editor):
    """Rename 'Default (traces)' -> 'Default - traces', etc."""
    ClusteringJob = apps.get_model("llm_analytics", "ClusteringJob")
    for old_suffix, new_name in [
        ("traces)", "Default - traces"),
        ("generations)", "Default - generations"),
    ]:
        ClusteringJob.objects.filter(name=f"Default ({old_suffix}").update(name=new_name)


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0018_migrate_clustering_configs_to_jobs"),
    ]

    operations = [
        migrations.RunPython(
            rename_default_clustering_jobs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
