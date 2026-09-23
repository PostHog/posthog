from django.db import migrations

BATCH_SIZE = 5000

# The `jsonb_typeof` guards mirror the isinstance checks in `SignalReportArtefact.latest_actionability`,
# so the migration and the receiver agree on a judgment whose fields carry the wrong JSON type.
BACKFILL_SQL = """
UPDATE signals_signalreport AS r
SET latest_actionability = j.actionability,
    latest_already_addressed = j.already_addressed
FROM (
    SELECT DISTINCT ON (a.report_id)
        a.report_id,
        CASE jsonb_typeof(x.c -> 'actionability') WHEN 'string' THEN x.c ->> 'actionability' END AS actionability,
        CASE jsonb_typeof(x.c -> 'already_addressed')
            WHEN 'boolean' THEN (x.c ->> 'already_addressed')::boolean
        END AS already_addressed
    FROM signals_signalreportartefact AS a
    CROSS JOIN LATERAL (SELECT a.content::jsonb AS c) AS x
    WHERE a.type = 'actionability_judgment'
      AND a.report_id = ANY(%(report_ids)s)
      AND left(a.content, 1) = '{'
      AND jsonb_typeof(x.c) = 'object'
    ORDER BY a.report_id, a.created_at DESC
) AS j
WHERE r.id = j.report_id
  AND (r.latest_actionability IS DISTINCT FROM j.actionability
       OR r.latest_already_addressed IS DISTINCT FROM j.already_addressed)
"""

NEXT_REPORT_IDS_SQL = """
SELECT id FROM signals_signalreport
WHERE (%(after)s::uuid IS NULL OR id > %(after)s::uuid)
ORDER BY id
LIMIT %(limit)s
"""


def backfill_latest_actionability(apps, schema_editor):
    """Fill the cached actionability of every report that already carries a judgment.

    The receivers that maintain the columns shipped in the previous release, so every judgment
    written since then is already on its row. This closes the rows written before that, in
    batches of reports so no single statement holds many row locks.
    """
    after = None
    with schema_editor.connection.cursor() as cursor:
        while True:
            cursor.execute(NEXT_REPORT_IDS_SQL, {"after": after, "limit": BATCH_SIZE})
            report_ids = [row[0] for row in cursor.fetchall()]
            if not report_ids:
                return
            cursor.execute(BACKFILL_SQL, {"report_ids": report_ids})
            after = report_ids[-1]


class Migration(migrations.Migration):
    # Non-atomic so each batch commits and releases its row locks as it goes.
    atomic = False

    dependencies = [
        ("signals", "0153_signalreport_latest_actionability"),
    ]

    # Reverse is a noop: clearing the columns would put every report back to "not judged".
    operations = [
        migrations.RunPython(backfill_latest_actionability, migrations.RunPython.noop, elidable=True),
    ]
