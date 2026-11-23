from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0251_signalgroupingrecord"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalgroupingrecord",
            index=models.Index(
                fields=["created_at"],
                name="signals_grouping_rec_created",
            ),
        ),
    ]
