from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid, ValidateConstraint

TABLE = "feature_flags_organizationfeatureflagsconfig"
CONSTRAINT = "org_ff_config_flag_evaluations_mode_valid"


class Migration(migrations.Migration):
    # VALIDATE must not run under the ALTER's ACCESS EXCLUSIVE lock, so each statement commits alone. Every operation
    # is safe to run again after a partial failure.
    atomic = False

    dependencies = [
        ("feature_flags", "0027_scheduledchange_team_record_idx"),
    ]

    # Mode 2 meant "flag evaluations only". It becomes mode 3, and mode 2 now means "read flag evaluations with no
    # events fallback". The constraint allows 3 before any row moves to it.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(model_name="organizationfeatureflagsconfig", name=CONSTRAINT),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}",
                    reverse_sql=f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} "
                    "CHECK (flag_evaluations_mode IN (0, 1, 2)) NOT VALID",
                ),
            ],
        ),
        AddConstraintNotValid(
            model_name="organizationfeatureflagsconfig",
            constraint=models.CheckConstraint(
                condition=models.Q(("flag_evaluations_mode__in", [0, 1, 2, 3])),
                name=CONSTRAINT,
            ),
        ),
        # Rolling back moves the new mode 2 to mode 1 first. The old code reads a stored 2 as "flag evaluations only"
        # and stops writing events for it, so mode 2 must not survive the rollback.
        migrations.RunSQL(
            sql=f"UPDATE {TABLE} SET flag_evaluations_mode = 3 WHERE flag_evaluations_mode = 2",
            reverse_sql=[
                f"UPDATE {TABLE} SET flag_evaluations_mode = 1 WHERE flag_evaluations_mode = 2",
                f"UPDATE {TABLE} SET flag_evaluations_mode = 2 WHERE flag_evaluations_mode = 3",
            ],
        ),
        ValidateConstraint(model_name="organizationfeatureflagsconfig", name=CONSTRAINT),
    ]
