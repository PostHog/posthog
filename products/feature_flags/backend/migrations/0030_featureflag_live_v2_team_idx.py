from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("feature_flags", "0029_teamfeatureflagsconfig_null_counts_as_not_set"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="featureflag",
            index=models.Index(
                fields=["team"],
                name="featureflag_live_v2_team_idx",
                condition=models.Q(filters__version=2) & ~models.Q(deleted=True),
            ),
        ),
    ]
