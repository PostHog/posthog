from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("experiments", "0040_experiment_feature_flag_rule_id_unique")]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="experimenttimeseriesrecalculation",
            name="posthog_exp_status_01657f_idx",
        ),
    ]
