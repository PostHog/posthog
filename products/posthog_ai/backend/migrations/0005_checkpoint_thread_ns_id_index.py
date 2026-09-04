from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog_ai", "0004_conversation_agent_runtime_conversation_task_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="conversationcheckpoint",
            index=models.Index(
                fields=["thread", "checkpoint_ns", "-id"],
                name="ee_conv_ckpt_thread_ns_id",
            ),
        ),
    ]
