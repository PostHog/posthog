from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0008_exportedasset_source_authentication"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="subscription",
            index=models.Index(
                fields=["next_delivery_date"],
                condition=models.Q(deleted=False, enabled=True),
                name="posthog_sub_due_enabled_idx",
            ),
        ),
    ]
