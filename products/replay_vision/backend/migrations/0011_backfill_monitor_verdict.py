from django.db import migrations

# Idempotent backfill: rewrites monitor observations' `verdict` from boolean to the literal
# strings 'yes' / 'no' so the persisted output JSON matches the new MonitorOutput schema.
# Replay vision is in closed beta with very low row counts, so a single UPDATE is fine.
_BACKFILL_SQL = """
UPDATE replay_vision_replayobservation
SET scanner_result = jsonb_set(
    scanner_result,
    '{model_output,verdict}',
    to_jsonb(CASE
        WHEN (scanner_result->'model_output'->>'verdict')::boolean THEN 'yes'
        ELSE 'no'
    END)
)
WHERE scanner_snapshot->>'scanner_type' = 'monitor'
  AND scanner_result IS NOT NULL
  AND scanner_result->'model_output' ? 'verdict'
  AND jsonb_typeof(scanner_result->'model_output'->'verdict') = 'boolean';
"""


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0010_replayscanner_last_seen_session_id"),
    ]

    operations = [
        migrations.RunSQL(sql=_BACKFILL_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
