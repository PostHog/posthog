from django.db import migrations

# Rows written before event_key existed carry an empty key, which the partial unique index
# excludes — so a webhook re-observing one of those PRs after deploy would announce it a
# second time. Backfilling the key from the payload closes that window, which is finite:
# only PRs already open at this deploy are affected.
#
# One statement, not batched: the filter is `event = 'pr_created'` on a per-task table, so
# the row count is small and bounded by the number of PRs tasks have ever opened while the
# announcement flag was on. The UPDATE joins on primary keys, so it takes row locks only.
BACKFILL_SQL = """
-- migration-analyzer: safe reason=Touches only pr_created rows in posthog_task_thread_message written before event_key existed - a few hundred at most - and updates them by primary key
WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY task_id, payload->>'pr_url' ORDER BY created_at, id
        ) AS rank
    FROM posthog_task_thread_message
    WHERE event = 'pr_created'
      AND event_key = ''
      AND payload->>'pr_url' IS NOT NULL
      AND payload->>'pr_url' <> ''
      -- event_key is varchar(255); a longer url stays unkeyed rather than failing the update.
      AND length(payload->>'pr_url') <= 255
)
UPDATE posthog_task_thread_message AS message
   SET event_key = message.payload->>'pr_url'
  FROM ranked
 WHERE message.id = ranked.id
   -- Only the first row of a duplicated pair takes the key; keying both would violate the
   -- unique index this backfill runs behind.
   AND ranked.rank = 1
"""

# Reversing re-empties only the keys this migration could have set, leaving rows written by
# the emitter (which never writes an event_key that isn't in its payload) untouched.
REVERSE_SQL = """
UPDATE posthog_task_thread_message
   SET event_key = ''
 WHERE event = 'pr_created'
   AND event_key <> ''
   AND event_key = payload->>'pr_url'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0085_taskthreadmessage_event_key_unique"),
    ]

    operations = [
        migrations.RunSQL(sql=BACKFILL_SQL, reverse_sql=REVERSE_SQL),
    ]
