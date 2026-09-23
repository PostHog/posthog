import json

from django.db import migrations, transaction

BATCH_SIZE = 1000

LOCK_REPORTS_SQL = """
SELECT id FROM signals_signalreport
WHERE id > %(after)s
ORDER BY id
LIMIT %(limit)s
FOR NO KEY UPDATE
"""

FIRST_REPORTS_SQL = """
SELECT id FROM signals_signalreport
ORDER BY id
LIMIT %(limit)s
FOR NO KEY UPDATE
"""

JUDGMENTS_SQL = """
SELECT report_id, content
FROM signals_signalreportartefact
WHERE type = 'actionability_judgment' AND report_id = ANY(%(report_ids)s)
ORDER BY report_id, created_at DESC
"""

UPDATE_SQL = """
UPDATE signals_signalreport AS r
SET latest_actionability = v.actionability,
    latest_already_addressed = v.already_addressed
FROM (VALUES %s) AS v(report_id, actionability, already_addressed)
WHERE r.id = v.report_id::uuid
  AND (r.latest_actionability IS DISTINCT FROM v.actionability
       OR r.latest_already_addressed IS DISTINCT FROM v.already_addressed)
"""


def _latest_values(contents: list[str]) -> tuple[str | None, bool | None] | None:
    # Same rule as SignalReportArtefact.latest_actionability: the newest row whose content is a
    # JSON object wins, and a field of the wrong type reads as NULL.
    for content in contents:
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        actionability = parsed.get("actionability")
        already_addressed = parsed.get("already_addressed")
        return (
            actionability if isinstance(actionability, str) else None,
            already_addressed if isinstance(already_addressed, bool) else None,
        )
    return None


def backfill_latest_actionability(apps, schema_editor):
    """Fill the cached actionability of every report that already carries a judgment.

    The receivers that maintain the columns shipped in the previous release, so every judgment
    written since is already on its row. This closes the rows written before that.

    Each batch locks its report rows FOR NO KEY UPDATE before reading the log, the same lock the
    receivers take, so a judgment written while the batch runs is either visible to the read or
    waits for the batch to commit. Content is parsed in Python so a malformed historical row is
    skipped rather than aborting the statement.
    """
    connection = schema_editor.connection
    after = None
    while True:
        with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
            if after is None:
                cursor.execute(FIRST_REPORTS_SQL, {"limit": BATCH_SIZE})
            else:
                cursor.execute(LOCK_REPORTS_SQL, {"after": after, "limit": BATCH_SIZE})
            report_ids = [row[0] for row in cursor.fetchall()]
            if not report_ids:
                return
            after = report_ids[-1]

            cursor.execute(JUDGMENTS_SQL, {"report_ids": report_ids})
            contents_by_report: dict[object, list[str]] = {}
            for report_id, content in cursor.fetchall():
                contents_by_report.setdefault(report_id, []).append(content)

            values = []
            for report_id, contents in contents_by_report.items():
                latest = _latest_values(contents)
                if latest is not None:
                    values.append((str(report_id), latest[0], latest[1]))
            if not values:
                continue
            placeholders = ", ".join(["(%s, %s, %s::boolean)"] * len(values))
            cursor.execute(UPDATE_SQL % placeholders, [item for value in values for item in value])


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
