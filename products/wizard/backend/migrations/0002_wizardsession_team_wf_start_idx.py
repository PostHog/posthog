from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("wizard", "0001_initial_wizard_session"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="wizardsession",
            index=models.Index(
                fields=["team", "workflow_id", "-started_at"],
                name="wizard_sess_team_wf_start_idx",
            ),
        ),
    ]
