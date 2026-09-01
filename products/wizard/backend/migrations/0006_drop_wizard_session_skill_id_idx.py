from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("wizard", "0005_wizardsession_handoff_text"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="wizardsession",
            name="wizard_wiza_team_id_ddd1dc_idx",
        ),
    ]
