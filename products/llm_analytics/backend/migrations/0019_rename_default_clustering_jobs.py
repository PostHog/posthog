from django.db import migrations


def rename_default_clustering_jobs(apps, schema_editor):
    """Rename 'Default (traces)' -> 'Default - traces', etc."""
    ClusteringJob = apps.get_model("llm_analytics", "ClusteringJob")
    for old_name, new_name in [
        ("Default (traces)", "Default - traces"),
        ("Default (generations)", "Default - generations"),
    ]:
        ClusteringJob.objects.filter(name=old_name).update(name=new_name)


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
