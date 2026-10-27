from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0140_drop_sandbox_session_team_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="AgentPeerMessage")],
            database_operations=[
                DropForeignKey("posthog_agent_peer_message", column=["sender_run_id", "target_run_id"]),
            ],
        ),
    ]
