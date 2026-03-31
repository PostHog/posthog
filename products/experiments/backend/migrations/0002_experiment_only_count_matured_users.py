from django.db import migrations, models


def migrate_metric_field_to_experiment(apps, schema_editor):
    """Move only_count_matured_users from per-metric JSON to experiment-level field.

    Scans experiments for metrics containing only_count_matured_users: true,
    sets the experiment-level field, and strips the key from metric dicts.
    """
    Experiment = apps.get_model("experiments", "Experiment")

    for experiment in Experiment.objects.all().iterator(chunk_size=1000):
        found = False
        for metrics_field in ("metrics", "metrics_secondary"):
            metrics = getattr(experiment, metrics_field) or []
            for metric in metrics:
                if metric.pop("only_count_matured_users", None):
                    found = True
        if found:
            experiment.only_count_matured_users = True
            experiment.save(update_fields=["only_count_matured_users", "metrics", "metrics_secondary"])


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0001_migrate_experiments_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="only_count_matured_users",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(migrate_metric_field_to_experiment, migrations.RunPython.noop),
    ]
