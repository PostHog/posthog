import uuid

from django.db import migrations

BATCH_SIZE = 10_000


def backfill_scanner_id(apps, schema_editor):
    """Attribute pre-existing receipts to their scanner, so a limit set mid-period counts the
    period's earlier spend instead of starting from zero. Receipts whose observation was already
    deleted have nothing to derive from and stay unattributed, as do pre-stack prompt-evaluation
    receipts, whose synthetic observation_id (uuid5 of suggestion/session/started_at, see
    prompt_evaluation.py) matches no observation row; that spend is bounded by the evaluation
    session cap and accepted. A follow-up migration in the notification PR repeats this pass to
    catch receipts written by old-code workers during the rolling deploy."""
    usage_table = apps.get_model("replay_vision", "ReplayObservationUsage")._meta.db_table
    observation_table = apps.get_model("replay_vision", "ReplayObservation")._meta.db_table
    # Keyset pagination on the pk: the null scanner_id rows have no index, so a plain LIMIT
    # loop would re-scan the table head on every batch.
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
            updated_ids = [row[0] for row in cursor.fetchall()]
            if not updated_ids:
                break
            last_id = max(updated_ids)
            if len(updated_ids) < BATCH_SIZE:
                break


class Migration(migrations.Migration):
    # Batches commit independently so the update never holds long locks on the receipt table.
    atomic = False

    dependencies = [
        ("replay_vision", "0069_validate_replay_scanner_credit_limit_positive"),
    ]

    operations = [
        migrations.RunPython(backfill_scanner_id, migrations.RunPython.noop, elidable=False),
    ]
