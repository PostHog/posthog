from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("notebooks", "0026_widget_snapshot"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="notebook",
            index=models.Index(fields=["short_id"], name="notebook_short_id_idx"),
        ),
    ]
