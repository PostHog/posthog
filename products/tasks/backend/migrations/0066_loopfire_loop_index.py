from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction; the constraint changes it depends on
    # stay transactional in 0065.
    atomic = False

    dependencies = [
        ("tasks", "0065_loop_hardening"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="loopfire",
            index=models.Index(fields=["loop", "created_at"], name="task_loop_fire_loop_ct_idx"),
        ),
    ]
