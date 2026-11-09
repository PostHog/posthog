from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0150_sandboxsession_park_reason_http_402"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["origin_product"],
                name="task_run_warm_pool_idx",
                condition=models.Q(status__in=["queued", "in_progress"], state__await_user_message=True),
            ),
        ),
    ]
