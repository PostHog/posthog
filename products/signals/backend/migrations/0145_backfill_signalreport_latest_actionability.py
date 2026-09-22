from django.db import migrations

BATCH_SIZE = 5000

# Reads the same value the inbox filters used to derive per request: the newest
# `actionability_judgment` artefact of the report, with the same guard against content that is not
# a JSON object. Batched by report primary key, and outside a transaction, so a long table never
# holds one lock for the whole walk.
BACKFILL = """
    UPDATE signals_signalreport r
    SET latest_actionability = latest.actionability,
        latest_already_addressed = latest.already_addressed
    FROM (
        SELECT DISTINCT ON (a.report_id)
            a.report_id,
            jsonb_extract_path_text(a.content::jsonb, 'actionability') AS actionability,
            jsonb_extract_path_text(a.content::jsonb, 'already_addressed') = 'true' AS already_addressed
        FROM signals_signalreportartefact a
        WHERE a.report_id = ANY(%s)
          AND a.type = 'actionability_judgment'
          AND a.content LIKE '{%%'
        ORDER BY a.report_id, a.created_at DESC
    ) latest
    WHERE r.id = latest.report_id
"""


def backfill_latest_actionability(apps, schema_editor):
    last_id = None
    with schema_editor.connection.cursor() as cursor:
        while True:
            if last_id is None:
                cursor.execute("SELECT id FROM signals_signalreport ORDER BY id LIMIT %s", [BATCH_SIZE])
            else:
                cursor.execute(
                    "SELECT id FROM signals_signalreport WHERE id > %s ORDER BY id LIMIT %s",
                    [last_id, BATCH_SIZE],
                )
            report_ids = [row[0] for row in cursor.fetchall()]
            if not report_ids:
                return
            cursor.execute(BACKFILL, [report_ids])
            last_id = report_ids[-1]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0144_signalreport_latest_actionability_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_latest_actionability, reverse_code=migrations.RunPython.noop),
    ]
