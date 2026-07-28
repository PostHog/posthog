from django.db import migrations

# Brex deprecated its Spend Limits v1 endpoints in favor of the v2 Budgets API. The source now
# defaults new instances to v2, and every product API this source reads already targets its current
# path (transactions/users on /v2, expenses/vendors on /v1, budgets on /v2), so v1 and v2 resolve to
# identical requests here — the repin is a pure pin move with no data/schema transform.
BREX_SOURCE_TYPE = "Brex"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_brex_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed (a customer intentionally pinned that schema) and are left alone — the
    # schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (now v2), so they need no update.
    # Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=BREX_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0104_easybill_source"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate v2 pins.
        migrations.RunPython(repin_brex_v1_to_v2, migrations.RunPython.noop, elidable=False),
    ]
