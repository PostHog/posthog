import uuid

from django.db import migrations

BATCH_SIZE = 10_000


def rebackfill_scanner_id(apps, schema_editor):
    """Repeat 0070's attribution pass: migrations run before pods roll, so old-code workers kept
    settling receipts without a scanner_id between 0070 running and the accounting deploy finishing.
    This PR deploys strictly after that rollout, so one more idempotent pass closes the window."""
    usage_table = apps.get_model("replay_vision", "ReplayObservationUsage")._meta.db_table
    observation_table = apps.get_model("replay_vision", "ReplayObservation")._meta.db_table
    last_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    with schema_editor.connection.cursor() as cursor:
        while True:
            cursor.execute(
                f"""
                WITH batch AS (
                    SELECT u.id AS usage_id, o.scanner_id AS scanner_id
                    FROM {usage_table} u
                    JOIN {observation_table} o ON o.id = u.observation_id
                    WHERE u.scanner_id IS NULL AND u.id > %(last_id)s
                    ORDER BY u.id
                    LIMIT {BATCH_SIZE}
                )
                UPDATE {usage_table} AS tgt
                SET scanner_id = batch.scanner_id
                FROM batch
                WHERE tgt.id = batch.usage_id
                RETURNING batch.usage_id
                """,
                {"last_id": last_id},
            )
            rows = cursor.fetchall()
            if not rows:
                break
            last_id = max(row[0] for row in rows)
            if len(rows) < BATCH_SIZE:
                break


class Migration(migrations.Migration):
    # Batches commit independently so the update never holds long locks on the receipt table.
    atomic = False

    dependencies = [
        ("replay_vision", "0072_replayscanner_limit_notified_period_start"),
    ]

    operations = [
        migrations.RunPython(rebackfill_scanner_id, migrations.RunPython.noop, elidable=False),
    ]
