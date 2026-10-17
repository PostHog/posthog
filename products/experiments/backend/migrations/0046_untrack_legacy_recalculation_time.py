from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [("experiments", "0045_alter_experimentmetricsrecalculation_trigger")]

    operations = [
        # Phase 1 of retiring the legacy single-time column. The field leaves model state
        # while the column stays, so pods on either release keep querying the table.
        # The DROP COLUMN follows in its own migration one deploy cycle later.
        untrack_field("teamexperimentsconfig", "experiment_recalculation_time"),
    ]
