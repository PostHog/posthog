from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0016_eventdefinition_scheduled_deletion_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                condition=models.Q(("scheduled_deletion_at__isnull", False)),
                fields=["scheduled_deletion_at"],
                name="posthog_eventdef_sched_del_idx",
            ),
        ),
    ]
