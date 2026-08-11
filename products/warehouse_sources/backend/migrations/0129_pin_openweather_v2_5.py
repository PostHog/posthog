from django.db import migrations

# OpenWeather now defaults to 3.0 (the One Call API). 3.0 serves a different product from the 2.5
# general-purpose APIs — different request paths (`/data/3.0/onecall`) and a different table set
# (current/hourly/daily instead of current_weather/forecast/air_pollution) — so moving a source
# from 2.5 to 3.0 is a lossy transition, not an in-place `api_version` flip, and also needs a One
# Call 3.0 subscription the stored key may not carry. That migration is therefore intentionally NOT
# scripted — existing sources keep their 2.5 pin.
#
# This migration only backs out the NULL cohort from the default flip. A NULL `api_version` resolves
# to `default_version`, which just moved 2.5 -> 3.0, so any OpenWeather source created without an
# explicit pin (direct-ORM/seeder paths that bypass the API's create-time stamping) would silently
# jump onto 3.0's divergent table set. Pinning those rows to 2.5 keeps them on the version they were
# syncing.
OPENWEATHER_SOURCE_TYPE = "OpenWeather"
V2_5_VERSION = "2.5"


def pin_openweather_v2_5(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pins only. Filtering on NULL keeps this idempotent — a re-run matches nothing,
    # and rows already carrying an explicit pin (2.5 or 3.0) are left as their owner set them.
    # Schema-level overrides (`ExternalDataSchema.api_version`) are customer-managed and untouched.
    ExternalDataSource.objects.filter(source_type=OPENWEATHER_SOURCE_TYPE, api_version__isnull=True).update(
        api_version=V2_5_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0128_repin_adobe_analytics_api_version_2_0")]

    operations = [
        # Reverse is a no-op: once pinned, a 2.5 row is indistinguishable from one natively stamped
        # 2.5, so re-nulling would wrongly clear legitimate explicit pins too.
        migrations.RunPython(pin_openweather_v2_5, migrations.RunPython.noop, elidable=False),
    ]
