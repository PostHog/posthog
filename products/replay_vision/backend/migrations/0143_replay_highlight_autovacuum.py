from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0142_replay_highlight_rank_tables"),
    ]

    operations = [
        # Vacuum after a small share of new or replaced rows, so the visibility map keeps index-only reads off the heap.
        migrations.RunSQL(
            sql="""
                ALTER TABLE replay_vision_replayobservationrank SET (
                    autovacuum_vacuum_insert_scale_factor = 0.02, autovacuum_vacuum_scale_factor = 0.02
                );
                ALTER TABLE replay_vision_replayhighlightfeedentry SET (
                    autovacuum_vacuum_insert_scale_factor = 0.02, autovacuum_vacuum_scale_factor = 0.02
                );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
