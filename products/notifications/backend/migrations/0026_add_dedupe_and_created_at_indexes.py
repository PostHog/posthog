from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("notifications", "0025_callable_choices"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="notificationevent",
            index=models.Index(
                fields=["notification_type", "target_type", "target_id", "resource_id", "source_id"],
                name="notification_event_dedupe_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="notificationevent",
            index=models.Index(fields=["created_at"], name="notification_event_created_at_idx"),
        ),
    ]
