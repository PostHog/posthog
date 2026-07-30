from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid, ValidateConstraint


class Migration(migrations.Migration):
    # NOT VALID add and VALIDATE must not share one transaction, or the ADD's ACCESS
    # EXCLUSIVE lock is held through the validation scan.
    atomic = False

    dependencies = [
        ("signals", "0075_signalscoutconfig_status"),
    ]

    operations = [
        AddConstraintNotValid(
            model_name="signalscoutconfig",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(enabled=True, status__in=("active", "pending_pause"))
                    | models.Q(enabled=False, status__in=("paused_by_system", "paused_by_user"))
                ),
                name="scout_config_enabled_matches_status",
            ),
        ),
        ValidateConstraint(
            model_name="signalscoutconfig",
            name="scout_config_enabled_matches_status",
        ),
    ]
