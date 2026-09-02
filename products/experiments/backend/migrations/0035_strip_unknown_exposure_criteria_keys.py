from django.db import migrations

BATCH_SIZE = 1000

# Writes used to accept unknown top-level exposure_criteria keys (e.g. `properties`, which
# belongs at exposure_config.properties). The query API parses stored criteria with a strict
# schema, so affected experiments fail every results/exposure query. Strip unknown keys from
# existing rows; the write path now rejects them, so bad data cannot reaccumulate.
# Frozen copy of posthog.schema.ExperimentExposureCriteria fields — migrations don't import app code.
ALLOWED_KEYS = (
    "activation_config",
    "exposure_config",
    "filterTestAccounts",
    "multiple_variant_handling",
)


def strip_unknown_exposure_criteria_keys(apps, schema_editor):
    Experiment = apps.get_model("experiments", "Experiment")

    # Unknown keys can't be expressed as a has_key filter, so walk every row with criteria
    # set — experiments are rare objects, this is a small table.
    experiment_ids = list(
        Experiment.objects.exclude(exposure_criteria=None).values_list("id", flat=True).order_by("id")
    )

    for start in range(0, len(experiment_ids), BATCH_SIZE):
        batch_ids = experiment_ids[start : start + BATCH_SIZE]
        to_update = []
        for experiment in Experiment.objects.filter(id__in=batch_ids).only("id", "exposure_criteria"):
            criteria = experiment.exposure_criteria
            if not criteria or not isinstance(criteria, dict):
                continue
            stripped = {k: v for k, v in criteria.items() if k in ALLOWED_KEYS}
            if stripped != criteria:
                experiment.exposure_criteria = stripped
                to_update.append(experiment)
        if to_update:
            Experiment.objects.bulk_update(to_update, ["exposure_criteria"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0034_backfill_precomputation_enabled_set_by"),
    ]

    operations = [
        migrations.RunPython(strip_unknown_exposure_criteria_keys, migrations.RunPython.noop),
    ]
