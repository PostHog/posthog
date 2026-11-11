from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [("signals", "0250_agent_run_output_and_spend_kinds")]

    operations = [
        ValidateConstraint(model_name="signalspend", name="signals_owner_spend_kind_owner_v3"),
        migrations.RunSQL("SET LOCAL lock_timeout = '1s'", reverse_sql=migrations.RunSQL.noop),
        migrations.RemoveConstraint(
            model_name="signalspend",
            name="signals_owner_spend_kind_owner_v2",
        ),
    ]
