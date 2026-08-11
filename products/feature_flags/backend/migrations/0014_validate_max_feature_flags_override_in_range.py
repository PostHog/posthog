from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0013_alter_teamfeatureflagsconfig_max_feature_flags_override_and_more"),
    ]

    operations = [
        # Phase 2 of the constraint added NOT VALID in 0013. Scans existing rows under
        # SHARE UPDATE EXCLUSIVE, so reads and writes keep running.
        ValidateConstraint(
            model_name="teamfeatureflagsconfig",
            name="max_feature_flags_override_in_range",
        ),
    ]
