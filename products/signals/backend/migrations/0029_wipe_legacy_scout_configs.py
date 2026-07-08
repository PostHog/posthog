from django.db import migrations


def _wipe_scout_configs(apps, schema_editor):
    # Old rows were one-per-team; the reshaped table is one-per-(team, skill). There's no
    # meaningful fan-out to preserve, and the table is dogfood-stage, so reset it — the
    # coordinator re-registers a row per scout skill on the next tick. Kept in its own
    # migration (separate transaction from the 0028 schema changes) so the data delete
    # doesn't share a transaction with the ALTER TABLEs.
    apps.get_model("signals", "SignalScoutConfig")._default_manager.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0028_reshape_scout_config_per_scout"),
    ]

    operations = [
        migrations.RunPython(_wipe_scout_configs, migrations.RunPython.noop),
    ]
