from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("error_tracking", "0017_migrate_cohorts_models"),
    ]

    operations = [
        # Add the composite first so `last_used` lookups keep index coverage
        # throughout, then drop the now-redundant single-column index.
        SafeAddIndexConcurrently(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["last_used", "created_at"], name="et_symset_used_created_idx"),
        ),
        SafeRemoveIndexConcurrently(
            model_name="errortrackingsymbolset",
            name="posthog_err_last_us_c924f6_idx",
        ),
    ]
