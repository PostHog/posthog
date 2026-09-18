import django.contrib.postgres.indexes
from django.db import migrations

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("experiments", "0040_experiment_feature_flag_rule_id_unique")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="experiment",
            index=django.contrib.postgres.indexes.GinIndex(fields=["metrics"], name="exp_metrics_gin", fastupdate=False),
        ),
        SafeAddIndexConcurrently(
            model_name="experiment",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["metrics_secondary"], name="exp_metrics_secondary_gin", fastupdate=False
            ),
        ),
    ]
