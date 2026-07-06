from django.db import migrations
from django.db.models import Q

BATCH_SIZE = 1000

# Feature-flag config now lives only on the linked FeatureFlag (the source of truth) and is
# projected into the deprecated `parameters` API field at read time. Strip these now-dead keys from
# existing rows' `parameters` blob. Re-running is a no-op once a row has none of the keys.
# Frozen copy of ExperimentService.FEATURE_FLAG_CONFIG_KEYS — migrations don't import app code.
FEATURE_FLAG_CONFIG_KEYS = (
    "feature_flag_variants",
    "rollout_percentage",
    "aggregation_group_type_index",
    "feature_flag_payloads",
    "ensure_experience_continuity",
)


def strip_feature_flag_config(apps, schema_editor):
    Experiment = apps.get_model("experiments", "Experiment")

    key_filter = Q()
    for key in FEATURE_FLAG_CONFIG_KEYS:
        key_filter |= Q(parameters__has_key=key)
    experiment_ids = list(Experiment.objects.filter(key_filter).values_list("id", flat=True).order_by("id"))

    for start in range(0, len(experiment_ids), BATCH_SIZE):
        batch_ids = experiment_ids[start : start + BATCH_SIZE]
        to_update = []
        for experiment in Experiment.objects.filter(id__in=batch_ids).only("id", "parameters"):
            parameters = experiment.parameters
            if not parameters:
                continue
            stripped = {k: v for k, v in parameters.items() if k not in FEATURE_FLAG_CONFIG_KEYS}
            if stripped != parameters:
                experiment.parameters = stripped
                to_update.append(experiment)
        if to_update:
            Experiment.objects.bulk_update(to_update, ["parameters"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0025_remove_teamexperimentsconfig_funnel_steps_data_disabled"),
    ]

    operations = [
        migrations.RunPython(strip_feature_flag_config, migrations.RunPython.noop),
    ]
