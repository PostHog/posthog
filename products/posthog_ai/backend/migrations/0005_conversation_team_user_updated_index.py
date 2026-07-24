from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog_ai", "0004_conversation_agent_runtime_conversation_task_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="conversation",
            index=models.Index(fields=["team", "user", "-updated_at"], name="conversation_team_user_updated"),
        ),
    ]
