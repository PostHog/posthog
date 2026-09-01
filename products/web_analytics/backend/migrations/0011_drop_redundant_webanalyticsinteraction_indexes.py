import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("web_analytics", "0010_contentautopilotrun_content_auto_run_active"),
    ]

    operations = [
        # Byte-for-byte duplicate of the `unique_web_analytics_interaction_per_kind` btree.
        SafeRemoveIndexConcurrently(
            model_name="webanalyticsinteraction",
            name="wa_interaction_team_user_idx",
        ),
        # Django's automatic foreign-key index. No query filters on team alone, so the planner
        # never picks it; the unique constraint serves every read and the cascade delete.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="webanalyticsinteraction",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_webanalyticsinteraction_team_id_92a53764",
                    table_name="posthog_webanalyticsinteraction",
                    columns="(team_id)",
                ),
            ],
        ),
    ]
