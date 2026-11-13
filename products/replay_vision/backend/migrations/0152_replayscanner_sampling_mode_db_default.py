from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0151_backfill_replayscanner_sweep_cadence"),
    ]

    operations = [
        migrations.AlterField(
            model_name="replayscanner",
            name="sampling_mode",
            field=models.CharField(
                choices=[("focused", "Focused"), ("balanced", "Balanced"), ("comprehensive", "Comprehensive")],
                db_default="comprehensive",
                default="comprehensive",
                help_text="Deprecated and ignored: every scanner scans as comprehensive. Only `retire_scanner_sampling_modes` reads or writes it.",
                max_length=20,
            ),
        ),
    ]
