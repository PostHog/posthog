from django.db import migrations, models


class Migration(migrations.Migration):
    # Plain nullable smallint -> metadata-only `ADD COLUMN ... NULL`, no table rewrite.
    # The column is DB-maintained by a trigger (see 0051); the backfill (0052) fills existing
    # rows, and the index (0053) is added concurrently afterwards.

    dependencies = [
        ("signals", "0049_turn_on_scout_source_by_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreportartefact",
            name="priority_rank",
            field=models.SmallIntegerField(blank=True, editable=False, null=True),
        ),
    ]
