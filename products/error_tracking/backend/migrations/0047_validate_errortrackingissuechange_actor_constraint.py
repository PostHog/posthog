from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0046_errortrackingissuechange_system_actor"),
    ]

    operations = [
        ValidateConstraint(model_name="errortrackingissuechange", name="et_issue_change_actor_matches_type"),
    ]
