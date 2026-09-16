from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0014_validate_subscription_context_team_fk"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="subscription",
            index=models.Index(
                fields=["next_delivery_date", "id"],
                condition=models.Q(deleted=False, enabled=True),
                name="posthog_sub_due_active_idx",
            ),
        ),
    ]
