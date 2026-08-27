from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index creation cannot run in a transaction.
    atomic = False

    dependencies = [
        ("exports", "0009_subscription_anchor_dashboard_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="subscription",
            index=models.Index(fields=["anchor_dashboard"], name="posthog_sub_anchor_dash_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="subscription",
            index=models.Index(fields=["anchor_insight"], name="posthog_sub_anchor_ins_idx"),
        ),
    ]
