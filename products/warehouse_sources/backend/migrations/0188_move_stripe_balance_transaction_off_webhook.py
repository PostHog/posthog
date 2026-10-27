from django.db import migrations

# Stripe sends no event that carries a `balance_transaction` object, so a BalanceTransaction table in
# webhook mode never receives a row: when the source has a webhook, every scheduled run reads 0
# webhook files and completes with 0 rows. When it has none, each run falls back to a full read with
# no watermark and re-reads, and bills, the whole table. The source stopped offering webhook sync
# for this table, but tables already set to webhook kept it. This moves them to what a new Stripe
# source picks for the table: append on `created`.
#
# Append rather than full refresh because full refresh re-reads, and bills, every balance
# transaction on each sync. Each moved table is reset so its next scheduled run deletes the table
# and imports every row once, which also fills the gap the webhook mode left. Without the reset,
# append has no watermark and would add every row again on top of the rows already there.
STRIPE_SOURCE_TYPE = "Stripe"
BALANCE_TRANSACTION_SCHEMA_NAME = "BalanceTransaction"


def move_balance_transaction_off_webhook(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # Matching only webhook rows keeps this idempotent: a second run matches nothing. Deleted schemas
    # and schemas of deleted sources never sync again, so they stay as they are. Paused schemas move
    # too, so a table that is turned back on reimports. `deleted` is nullable, hence exclude.
    schemas = (
        ExternalDataSchema.objects.filter(
            source__source_type=STRIPE_SOURCE_TYPE,
            name=BALANCE_TRANSACTION_SCHEMA_NAME,
            sync_type="webhook",
        )
        .exclude(deleted=True)
        .exclude(source__deleted=True)
    )
    for schema in schemas.iterator():
        schema.sync_type = "append"
        schema.sync_type_config = {
            **(schema.sync_type_config or {}),
            "incremental_field": "created",
            "incremental_field_type": "integer",
            "reset_pipeline": True,
        }
        schema.save(update_fields=["sync_type", "sync_type_config"])


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0187_repin_teamtailor_api_version"),
    ]

    operations = [
        # Reverse is a no-op: moving these tables back to webhook would stop them updating again.
        migrations.RunPython(move_balance_transaction_off_webhook, migrations.RunPython.noop, elidable=True),
    ]
