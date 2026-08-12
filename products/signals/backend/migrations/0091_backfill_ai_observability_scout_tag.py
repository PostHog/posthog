from django.db import migrations

# One-off catch-up for the `scout-tags` frontmatter the AI observability scout now declares.
# `register_missing_configs` stamps canonical tags at creation only, so without this every team
# seeded before that change keeps an untagged config and the scout stays out of AI observability's
# scout list. Additive and idempotent — appends nothing to a row that already carries the tag, and
# leaves any other tags on the row alone.
_SKILL_NAME = "signals-scout-ai-observability"
_TAG = "ai-observability"

# `SignalScoutConfig.MAX_TAGS` at the time of writing. A row already at the cap is skipped rather
# than pushed over it, which would 400 the next tag edit through the API.
_MAX_TAGS = 10

FORWARD_SQL = f"""
    UPDATE signals_signalscoutconfig
    SET tags = COALESCE(tags, '{{}}') || ARRAY['{_TAG}']::varchar[]
    WHERE skill_name = '{_SKILL_NAME}'
      AND NOT (COALESCE(tags, '{{}}') @> ARRAY['{_TAG}']::varchar[])
      AND CARDINALITY(COALESCE(tags, '{{}}')) < {_MAX_TAGS}
"""

# Reverse strips the tag back off so a rollback leaves no trace of the backfill. A person who
# added the tag by hand loses it here; that is the honest inverse of an unconditional append.
REVERSE_SQL = f"""
    UPDATE signals_signalscoutconfig
    SET tags = ARRAY_REMOVE(tags, '{_TAG}')
    WHERE skill_name = '{_SKILL_NAME}'
      AND tags @> ARRAY['{_TAG}']::varchar[]
"""


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0090_signal_scout_run_recent_idx"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
