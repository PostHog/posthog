from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0006_remove_evaluation_prompt"),
    ]

    operations = [
        # Drop the deprecated prompt column from the database
        # The prompt data was migrated to evaluation_config in migration 0004
        # The field was removed from Django's state in migration 0006 (deployed in PR #40089)
        # This is the final cleanup step after one full deployment cycle
        migrations.RemoveField(
            model_name="evaluation",
            name="prompt",
        ),
    ]
