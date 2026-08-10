from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0084_taskthreadmessage_event_key"),
    ]

    operations = [
        # The constraint exists in Django state only; the index behind it is built
        # concurrently so writers to posthog_task_thread_message keep running.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="taskthreadmessage",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("event_key", ""), _negated=True),
                        fields=("task", "event", "event_key"),
                        name="task_thread_msg_event_key_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="task_thread_msg_event_key_uniq",
                    table_name="posthog_task_thread_message",
                    columns="(task_id, event, event_key)",
                    unique=True,
                    where="WHERE event_key <> ''",
                ),
            ],
        ),
    ]
