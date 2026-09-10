from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0012_alter_subscription_created_by_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="subscription",
            index=models.Index(
                fields=["team", "next_delivery_date", "id"],
                name="posthog_sub_team_due_sched",
                condition=models.Q(enabled=True, deleted=False, next_delivery_date__isnull=False),
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="subscription",
            index=models.Index(
                fields=["next_delivery_date", "id"],
                name="posthog_sub_due_schedule",
                condition=models.Q(enabled=True, deleted=False, next_delivery_date__isnull=False),
            ),
        ),
    ]
