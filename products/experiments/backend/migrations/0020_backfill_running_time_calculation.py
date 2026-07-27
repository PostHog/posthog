from django.db import migrations
from django.db.models import Q

BATCH_SIZE = 1000

CALCULATOR_KEYS = (
    "minimum_detectable_effect",
    "recommended_running_time",
    "recommended_sample_size",
    "exposure_estimate_config",
)


def backfill_running_time_calculation(apps, schema_editor):
    Experiment = apps.get_model("experiments", "Experiment")

    # Only rows with calculator data in `parameters` and no value in the new field yet,
    # so re-running is a no-op and rows already dual-written by the API are skipped.
    base_queryset = Experiment.objects.filter(parameters__has_any_keys=list(CALCULATOR_KEYS)).filter(
        Q(running_time_calculation__isnull=True) | Q(running_time_calculation={})
    )
    experiment_ids = list(base_queryset.values_list("id", flat=True).order_by("id"))

    for start in range(0, len(experiment_ids), BATCH_SIZE):
        batch_ids = experiment_ids[start : start + BATCH_SIZE]
        to_update = []
        for experiment in Experiment.objects.filter(id__in=batch_ids).only("id", "parameters"):
            parameters = experiment.parameters or {}
            calculation = {key: parameters[key] for key in CALCULATOR_KEYS if key in parameters}
            if not calculation:
                continue
            experiment.running_time_calculation = calculation
            to_update.append(experiment)
        if to_update:
            Experiment.objects.bulk_update(to_update, ["running_time_calculation"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0019_experiment_running_time_calculation"),
    ]

    operations = [
        migrations.RunPython(backfill_running_time_calculation, migrations.RunPython.noop),
    ]
