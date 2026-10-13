from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1_000
LOG_EVERY_BATCHES = 25

# Keyset-paginated over the primary key rather than hunting for the NULLs, so the scan stays
# linear before the new column has an index leading on it. The `IS NULL` guard makes a
# `bin/migrate` retry safe: a task the new signals have already stamped keeps its live value
# instead of being pulled back to this historical estimate.
BACKFILL_SQL = """
UPDATE posthog_task AS t
   SET last_activity_at = GREATEST(
           t.updated_at,
           (SELECT MAX(r.updated_at) FROM posthog_task_run r WHERE r.task_id = t.id)
       )
 WHERE t.id = ANY(%s)
   AND t.last_activity_at IS NULL
"""


def backfill_last_activity_at(apps, schema_editor):
    """Seed the activity clock from what existing rows already know about themselves.

    The task's own ``updated_at`` and its newest run's ``updated_at`` are the closest thing
    history carries to "when something last happened here", since a run's timestamp moves while
    it streams and the task's does not. Postgres ``GREATEST`` ignores NULLs, so a task with no
    runs falls back to its own ``updated_at``.
    """
    last_id = "00000000-0000-0000-0000-000000000000"
    batches = 0
    with schema_editor.connection.cursor() as cursor:
        while True:
            cursor.execute("SELECT id FROM posthog_task WHERE id > %s ORDER BY id LIMIT %s", [last_id, BATCH_SIZE])
            task_ids = [row[0] for row in cursor.fetchall()]
            if not task_ids:
                logger.info("task_last_activity_backfill_completed", batches=batches)
                return
            last_id = task_ids[-1]
            cursor.execute(BACKFILL_SQL, [task_ids])
            batches += 1
            if batches % LOG_EVERY_BATCHES == 0:
                logger.info("task_last_activity_backfill_progress", batches=batches)


class Migration(migrations.Migration):
    # Keeps each backfill batch on its own transaction rather than holding one open across the
    # whole historical scan.
    atomic = False

    dependencies = [("tasks", "0091_task_last_activity_at")]

    operations = [
        migrations.RunPython(backfill_last_activity_at, migrations.RunPython.noop, elidable=True),
    ]
