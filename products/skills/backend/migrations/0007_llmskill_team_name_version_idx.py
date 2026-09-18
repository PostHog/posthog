from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("skills", "0006_llmskill_version_description"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="llmskill",
            index=models.Index(fields=["team", "name", "-version"], name="llm_skill_team_name_ver_idx"),
        ),
    ]
