import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0184_signalscratchpad_search_trgm_indexes")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(name="signalspend", table="signals_signalspend"),
                migrations.RenameModel(old_name="SignalSpend", new_name="LegacySignalSpend"),
                migrations.AlterField(
                    model_name="legacysignalspend",
                    name="scout_run",
                    field=models.ForeignKey(
                        to="signals.signalscoutrun",
                        on_delete=django.db.models.deletion.CASCADE,
                        null=True,
                        blank=True,
                        related_name="+",
                    ),
                ),
            ],
        ),
    ]
