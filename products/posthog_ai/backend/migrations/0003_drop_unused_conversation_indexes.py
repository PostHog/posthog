from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog_ai", "0002_alter_agentartifact_team_alter_conversation_team_and_more"),
    ]

    operations = [
        # Every read that orders by `-updated_at` filters by team or user first, so the
        # planner takes those indexes instead and this one only costs write amplification.
        SafeRemoveIndexConcurrently(
            model_name="conversation",
            name="ee_conversa_updated_19e4e6_idx",
        ),
        # `agent_runtime` holds two values and no query filters on it. The `_like`
        # companion is Django boilerplate for `LIKE 'x%'` scans that nothing runs.
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
