from django.db import migrations
from django.db.models import Q

BATCH_SIZE = 1000


def backfill_excluded_variants(apps, schema_editor):
    Experiment = apps.get_model("experiments", "Experiment")

    # AddField defaults existing rows to [], so copy the legacy parameters.excluded_variants
    # into the new column for rows that actually have exclusions. Re-running is a no-op:
    # once a row's column is populated it no longer matches the empty/null guard.
    base_queryset = Experiment.objects.filter(parameters__has_key="excluded_variants").filter(
        Q(excluded_variants__isnull=True) | Q(excluded_variants=[])
    )
    experiment_ids = list(base_queryset.values_list("id", flat=True).order_by("id"))

    for start in range(0, len(experiment_ids), BATCH_SIZE):
        batch_ids = experiment_ids[start : start + BATCH_SIZE]
        to_update = []
        for experiment in Experiment.objects.filter(id__in=batch_ids).only("id", "parameters", "excluded_variants"):
            value = (experiment.parameters or {}).get("excluded_variants")
            if not value:  # legacy empty/None — the column default [] already matches
                continue
            experiment.excluded_variants = list(value)
            to_update.append(experiment)
        if to_update:
            Experiment.objects.bulk_update(to_update, ["excluded_variants"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0023_experiment_excluded_variants"),
    ]

    operations = [
        migrations.RunPython(backfill_excluded_variants, migrations.RunPython.noop),
    ]
