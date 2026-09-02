from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0080_reconcile_scout_status_enabled"),
    ]

    operations = [
        AddConstraintNotValid(
            model_name="signalscoutconfig",
            constraint=models.CheckConstraint(
                name="scout_config_enabled_matches_status",
                condition=models.Q(enabled=True, status__in=["active", "pending_pause"])
                | models.Q(enabled=False, status__in=["paused_by_system", "paused_by_user"]),
            ),
        ),
        AddConstraintNotValid(
            model_name="signalscoutconfig",
            constraint=models.CheckConstraint(
                name="scout_config_pause_reason_matches_status",
                condition=models.Q(status__in=["pending_pause", "paused_by_system"], pause_reason__isnull=False)
                | models.Q(status__in=["active", "paused_by_user"], pause_reason__isnull=True),
            ),
        ),
    ]
