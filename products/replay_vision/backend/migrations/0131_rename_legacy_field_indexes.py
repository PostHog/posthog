from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0130_rom_small_asset_idx"),
    ]

    operations = [
        # Databases from before the replaylensobservation rename hold these under the old table's names.
        migrations.RunSQL(
            sql=[
                "ALTER INDEX IF EXISTS replay_vision_replaylensobservation_team_id_b10decc8 "
                "RENAME TO replay_vision_replayobservation_team_id_b204b330",
                "ALTER INDEX IF EXISTS replay_vision_replaylensobservation_lens_id_4a4cd5c2 "
                "RENAME TO replay_vision_replayobservation_scanner_id_f2400b26",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
