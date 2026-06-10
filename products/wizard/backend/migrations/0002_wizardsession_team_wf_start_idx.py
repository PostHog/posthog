from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("wizard", "0001_initial_wizard_session"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="wizardsession",
                    index=models.Index(
                        fields=["team", "workflow_id", "-started_at"],
                        name="wizard_sess_team_wf_start_idx",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="wizard_sess_team_wf_start_idx",
                    table_name="wizard_wizardsession",
                    columns="(team_id, workflow_id, started_at DESC)",
                ),
            ],
        ),
    ]
