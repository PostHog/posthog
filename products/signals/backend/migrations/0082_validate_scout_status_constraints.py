from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0081_scout_status_constraints"),
    ]

    operations = [
        ValidateConstraint(model_name="signalscoutconfig", name="scout_config_enabled_matches_status"),
        ValidateConstraint(model_name="signalscoutconfig", name="scout_config_pause_reason_matches_status"),
    ]
