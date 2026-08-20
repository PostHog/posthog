from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    # VALIDATE runs under SHARE UPDATE EXCLUSIVE (does not block reads or writes). Kept in its
    # own migration so 0066's NOT VALID add commits and releases its ACCESS EXCLUSIVE lock first,
    # rather than holding it across the validation scan.
    dependencies = [
        ("replay_vision", "0068_scanner_usage_scanner_id_index"),
    ]

    operations = [
        ValidateConstraint(
            model_name="replayscanner",
            name="replay_scanner_credit_limit_positive",
        ),
    ]
