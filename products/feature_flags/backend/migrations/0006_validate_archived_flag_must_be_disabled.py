from django.db import migrations

from posthog.migration_helpers.not_valid_constraint import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0005_featureflag_archived_disabled_constraint"),
    ]

    operations = [
        ValidateConstraint(model_name="featureflag", name="archived_flag_must_be_disabled"),
    ]
