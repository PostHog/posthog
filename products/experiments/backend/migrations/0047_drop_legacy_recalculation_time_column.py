from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("experiments", "0046_untrack_legacy_recalculation_time")]

    operations = [
        # Phase 2 of retiring the legacy single-time column. 0046 removed the field from
        # model state one deploy cycle ago, so no running pod names the column any more.
        migrations.RunSQL(
            sql='ALTER TABLE "experiments_teamexperimentsconfig" DROP COLUMN IF EXISTS "experiment_recalculation_time";',
            reverse_sql='ALTER TABLE "experiments_teamexperimentsconfig" ADD COLUMN IF NOT EXISTS "experiment_recalculation_time" time NULL;',
        ),
    ]
