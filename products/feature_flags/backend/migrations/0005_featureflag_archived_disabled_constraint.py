from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers.not_valid_constraint import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0004_featureflag_archived"),
    ]

    operations = [
        AddConstraintNotValid(
            model_name="featureflag",
            constraint=models.CheckConstraint(
                condition=~Q(archived=True, active=True), name="archived_flag_must_be_disabled"
            ),
        ),
    ]
