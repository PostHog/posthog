from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0009_subscription_delivery_config"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="subscriptiondelivery",
            index=models.Index(
                fields=["subscription", "status", "-created_at"],
                name="posthog_subdel_sub_st_crtd",
            ),
        ),
    ]
