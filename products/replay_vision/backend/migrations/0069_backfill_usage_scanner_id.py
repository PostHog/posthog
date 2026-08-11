from django.db import migrations

BATCH_SIZE = 10_000


def backfill_scanner_id(apps, schema_editor):
    """Attribute pre-existing receipts to their scanner, so a limit set mid-period counts the
    period's earlier spend instead of starting from zero. Receipts whose observation was already
    deleted have nothing to derive from and stay unattributed."""
    usage_table = apps.get_model("replay_vision", "ReplayObservationUsage")._meta.db_table
    observation_table = apps.get_model("replay_vision", "ReplayObservation")._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        while True:
            cursor.execute(
                f"""
                WITH batch AS (
                    SELECT u.id AS usage_id, o.scanner_id AS scanner_id
                    FROM {usage_table} u
                    JOIN {observation_table} o ON o.id = u.observation_id
                    WHERE u.scanner_id IS NULL
                    LIMIT {BATCH_SIZE}
                )
                UPDATE {usage_table} AS tgt
                SET scanner_id = batch.scanner_id
                FROM batch
                WHERE tgt.id = batch.usage_id
                """
            )
            if cursor.rowcount < BATCH_SIZE:
                break


class Migration(migrations.Migration):
    # Batches commit independently so the update never holds long locks on the receipt table.
    atomic = False

    dependencies = [
        ("replay_vision", "0068_validate_replay_scanner_credit_limit_positive"),
    ]

    operations = [
        migrations.RunPython(backfill_scanner_id, migrations.RunPython.noop, elidable=False),
    ]
