from django.db import migrations

# Stored scanner queries are validated against the recordings query schema, which no longer has the relevance sort or
# filter, so a leftover key would fail every read of the scanner. Removing keys inside one UPDATE keeps concurrent edits.
DROP_RETIRED_SCANNER_QUERY_FIELDS = """
UPDATE replay_vision_replayscanner
SET query = CASE WHEN query->>'order' = 'surfacing_score' THEN query - 'order' ELSE query END - 'recommended_only'
WHERE query->>'order' = 'surfacing_score' OR query ? 'recommended_only'
"""

DROP_RETIRED_BACKFILL_QUERY_FIELDS = """
UPDATE replay_vision_replayscannerbackfill
SET scanner_snapshot = jsonb_set(
    scanner_snapshot,
    '{query}',
    CASE
        WHEN scanner_snapshot->'query'->>'order' = 'surfacing_score' THEN (scanner_snapshot->'query') - 'order'
        ELSE scanner_snapshot->'query'
    END - 'recommended_only'
)
WHERE scanner_snapshot->'query'->>'order' = 'surfacing_score' OR scanner_snapshot->'query' ? 'recommended_only'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0152_replayscanner_sampling_mode_db_default"),
    ]

    operations = [
        migrations.RunSQL(DROP_RETIRED_SCANNER_QUERY_FIELDS, migrations.RunSQL.noop, elidable=True),
        migrations.RunSQL(DROP_RETIRED_BACKFILL_QUERY_FIELDS, migrations.RunSQL.noop, elidable=True),
    ]
