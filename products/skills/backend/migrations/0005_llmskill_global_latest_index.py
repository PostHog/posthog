from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("skills", "0004_llmskill_is_global"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="llmskill",
            index=models.Index(
                condition=models.Q(("deleted", False), ("is_global", True), ("is_latest", True)),
                fields=["name"],
                name="llm_skill_global_latest",
            ),
        ),
    ]
