from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0004_subscription_ai_prompt_config"),
        ("posthog", "1247_oauthaccesstoken_token_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="subscriptiondelivery",
            index=models.Index(
                fields=["subscription", "status", "-finished_at"],
                name="posthog_subdel_sub_fin",
            ),
        ),
    ]
