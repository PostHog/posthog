from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("feature_flags", "0014_clean_flag_filters_inert_violations"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="featureflag",
            index=models.Index(fields=["team", "-created_at"], name="ff_team_id_created_at_idx"),
        ),
    ]
