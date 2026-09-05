from django.db import migrations

# Shopify keeps each quarterly version accessible for about 12 months. "2025-10" stops being
# accessible on 2026-10-16 15:00 UTC, after which Shopify falls forward to the oldest accessible
# version instead of returning an error — so a pin left behind moves silently rather than failing
# loudly, which is exactly what the pinning framework exists to prevent. This repins source-level
# pins from "2025-10" to "2026-07" (the current default).
#
# No data or schema transform accompanies the repin: the source builds one shared set of GraphQL
# documents and sends the version only as the Admin API URL segment, so a repinned source requests
# the same fields, and produces the same columns, as a source created on "2026-07" today.
SHOPIFY_SOURCE_TYPE = "Shopify"
SHOPIFY_API_VERSION_2025_10 = "2025-10"
SHOPIFY_API_VERSION_2026_07 = "2026-07"


def repin_shopify_2025_10_to_2026_07(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed
    # (a customer intentionally pinned that schema) and are left alone — the schema-level deprecation
    # warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` ("2026-07"), so they need no update.
    # Matching only `api_version="2025-10"` keeps this idempotent: a second run matches nothing.
    # ExternalDataSource is one row per configured source, so a single bulk update is quick.
    ExternalDataSource.objects.filter(source_type=SHOPIFY_SOURCE_TYPE, api_version=SHOPIFY_API_VERSION_2025_10).update(
        api_version=SHOPIFY_API_VERSION_2026_07
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0160_datawarehousetable_dwtable_team_live_created"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "2026-07" rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate "2026-07" pins and move customers back
        # onto the sunset version.
        migrations.RunPython(repin_shopify_2025_10_to_2026_07, migrations.RunPython.noop, elidable=True),
    ]
