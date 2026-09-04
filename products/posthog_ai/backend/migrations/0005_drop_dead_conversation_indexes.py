from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog_ai", "0004_conversation_agent_runtime_conversation_task_and_more"),
    ]

    operations = [
        # `updated_at` index: never served a read. The list endpoint sorts after the
        # user FK index, and the compaction sweep matches too much of the table to use it.
        SafeRemoveIndexConcurrently(
            model_name="conversation",
            name="ee_conversa_updated_19e4e6_idx",
        ),
        # `agent_runtime` index (and its varchar_pattern_ops `_like` twin) from
        # `db_index=True`: no queryset filters on the column, so neither is reachable.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="conversation",
                    name="agent_runtime",
                    field=models.CharField(
                        choices=[("langgraph", "LangGraph"), ("sandbox", "Sandbox")],
                        default="langgraph",
                        help_text="Runtime that owns this conversation for its whole life. Stamped at create time from the phai-sandbox-mode flag; never re-evaluated.",
                        max_length=16,
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="ee_conversation_agent_runtime_516eb9f8",
                    table_name="ee_conversation",
                    columns="(agent_runtime)",
                ),
                DropIndexConcurrently(
                    index_name="ee_conversation_agent_runtime_516eb9f8_like",
                    table_name="ee_conversation",
                    columns="(agent_runtime varchar_pattern_ops)",
                ),
            ],
        ),
    ]
