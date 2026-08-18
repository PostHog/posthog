import time

from django.db import migrations

# Migration 0052 wrote a 30-day incremental lookback onto every existing Google Ads incremental
# schema, and the source default handed the same value to schemas created after it shipped. Nobody
# asked for either: the window turned every incremental run into a trailing-month re-read, multiplying
# reported rows on the big stats tables and pushing warehouse spend up on accounts that had changed
# nothing. Drop it so those schemas go back to reading only new days, and let the (now much smaller)
# source default apply to schemas created from here on.
#
# 30 days is also the value a user could have typed into the sync method form, and once persisted the
# two are indistinguishable. Clearing it costs such a user a setting they can re-enter, whereas
# leaving it keeps every unwitting account paying for the re-read, so match on the value.
BACKFILLED_LOOKBACK_SECONDS = 30 * 24 * 60 * 60

LOOKBACK_KEY = "incremental_field_lookback_seconds"
GOOGLE_ADS_SOURCE_TYPE = "GoogleAds"
BATCH_SIZE = 1000


def drop_backfilled_google_ads_lookback(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    schema_table = ExternalDataSchema._meta.db_table
    source_table = ExternalDataSource._meta.db_table

    # Removing the key with jsonb `-` keeps each batch a single statement. Reading the config into
    # Python and writing it back would race the syncs running right now, which write their cursor
    # into this same column — losing one reverts a schema to a genuine full sync, the outcome this
    # migration exists to avoid.
    #
    # Soft-deleted rows are included: 0052 skipped them, but the creation-path default did not, and a
    # restored schema should not resume on the wide window.
    #
    # Updated rows stop matching the filter, so `LIMIT` alone advances the loop and re-running the
    # migration is a no-op.
    sql = f"""
        UPDATE {schema_table}
        SET sync_type_config = sync_type_config - %(key)s
        WHERE id IN (
            SELECT sch.id
            FROM {schema_table} sch
            JOIN {source_table} src ON src.id = sch.source_id
            WHERE src.source_type = %(source_type)s
              AND sch.sync_type = 'incremental'
              AND sch.sync_type_config ->> %(key)s = %(lookback)s
            LIMIT {BATCH_SIZE}
        )
    """
    params = {
        "key": LOOKBACK_KEY,
        "source_type": GOOGLE_ADS_SOURCE_TYPE,
        # `->>` yields text, so compare against the stored number as text rather than casting the
        # column — a non-numeric value in that key would make a ::int cast error out mid-migration.
        "lookback": str(BACKFILLED_LOOKBACK_SECONDS),
    }

    with schema_editor.connection.cursor() as cursor:
        while True:
            cursor.execute(sql, params)
            if not cursor.rowcount:
                break
            time.sleep(0.1)


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0140_scaffold_samcart_source")]

    operations = [
        # Reverse is a no-op: re-adding the window is the regression, and a cleared schema is
        # indistinguishable from one that never had the key.
        migrations.RunPython(drop_backfilled_google_ads_lookback, migrations.RunPython.noop, elidable=False),
    ]
