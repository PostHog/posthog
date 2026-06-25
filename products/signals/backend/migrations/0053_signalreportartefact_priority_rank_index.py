from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("signals", "0052_backfill_priority_rank"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(
                fields=["team", "priority_rank", "-created_at", "report"],
                name="signals_artefact_prio_idx",
                condition=models.Q(("type", "priority_judgment")),
            ),
        ),
    ]
