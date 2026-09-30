from django.db import migrations


def backfill_recalculation_times(apps, schema_editor):
    # Rows exist only for teams that touched experiment settings, so this stays small.
    TeamExperimentsConfig = apps.get_model("experiments", "TeamExperimentsConfig")
    for config in TeamExperimentsConfig.objects.exclude(experiment_recalculation_time=None).filter(
        experiment_recalculation_times__isnull=True
    ):
        config.experiment_recalculation_times = [f"{config.experiment_recalculation_time.hour:02d}:00:00"]
        config.save(update_fields=["experiment_recalculation_times"])


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0042_teamexperimentsconfig_experiment_recalculation_times_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_recalculation_times, migrations.RunPython.noop, elidable=True),
    ]
