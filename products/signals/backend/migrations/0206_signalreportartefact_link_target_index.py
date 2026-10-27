from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0205_signalreportartefact_link_target"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(
                condition=models.Q(("type", "report_link")),
                fields=["link_target_id"],
                name="signals_link_target_idx",
            ),
        ),
    ]
