from django.db import migrations


def migrate_metric_field_to_experiment(apps, schema_editor):
    """Move only_count_matured_users from per-metric JSON to experiment-level field.

    Scans experiments for metrics containing only_count_matured_users,
    sets the experiment-level field, and strips the key from metric dicts.
    """
    Experiment = apps.get_model("experiments", "Experiment")

    for experiment in Experiment.objects.all().iterator(chunk_size=1000):
        found = False
        modified = False
        for metrics_field in ("metrics", "metrics_secondary"):
            metrics = getattr(experiment, metrics_field) or []
            for metric in metrics:
                popped = metric.pop("only_count_matured_users", None)
                if popped is not None:
                    modified = True
                    if popped:
                        found = True
        if modified:
            experiment.only_count_matured_users = found
            experiment.save(update_fields=["only_count_matured_users", "metrics", "metrics_secondary"])


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0002_experiment_only_count_matured_users"),
    ]

    operations = [
        migrations.RunPython(migrate_metric_field_to_experiment, migrations.RunPython.noop),
    ]
