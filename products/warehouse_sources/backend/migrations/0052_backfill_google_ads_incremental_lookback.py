import time

from django.db import migrations

# Keep in sync with GOOGLE_ADS_STATS_INCREMENTAL_LOOKBACK_SECONDS in the Google Ads source
# (products/warehouse_sources/.../sources/google_ads/source.py). Inlined here so this
# point-in-time backfill stays self-contained and doesn't import app code that may change.
DEFAULT_LOOKBACK_SECONDS = 30 * 24 * 60 * 60  # 30 days

BATCH_SIZE = 1000


def backfill_google_ads_lookback(apps, schema_editor):
    # Existing Google Ads incremental stats schemas were created before the source set a
    # default lookback, so they re-fetch only the newest day and freeze every prior day at
    # its first-imported, not-yet-final value. Give them the same overlap re-read window new
    # schemas now get. Only the incremental schemas matter — the lookback is a no-op on
    # full_refresh, which re-reads everything anyway.
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    base_qs = (
        ExternalDataSchema.objects.filter(
            source__source_type="GoogleAds",
            sync_type="incremental",
            deleted=False,
        )
        .order_by("id")
        .only("id", "sync_type_config")
    )

    last_id = None
    while True:
        batch_qs = base_qs if last_id is None else base_qs.filter(id__gt=last_id)
        batch = list(batch_qs[:BATCH_SIZE])
        if not batch:
            break

        to_update = []
        for schema in batch:
            config = schema.sync_type_config or {}
            # Only set it when absent — preserve an explicit user value, including 0
            # ("no overlap re-read"), so absence is the sole trigger and reruns are idempotent.
            if "incremental_field_lookback_seconds" not in config:
                config["incremental_field_lookback_seconds"] = DEFAULT_LOOKBACK_SECONDS
                schema.sync_type_config = config
                to_update.append(schema)

        if to_update:
            ExternalDataSchema.objects.bulk_update(to_update, ["sync_type_config"])

        last_id = batch[-1].id
        time.sleep(0.1)


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0051_warehousecolumnstatistics")]

    operations = [
        migrations.RunPython(backfill_google_ads_lookback, migrations.RunPython.noop, elidable=True),
    ]
