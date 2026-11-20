from importlib import import_module

from django.db import migrations

# Rerun of 0184, which keeps a v1/v2 source on its pin while a live `traces` or `sessions` schema still
# syncs, because v3 drops both tables. On the 2026-11-16 sunset, Langfuse Cloud started to answer those
# routes with a 410 Gone, which is non-retryable, so the sync turned those schemas off. The rerun moves
# every source whose legacy schemas are all off, whatever turned them off. A source that still syncs
# either table, such as one on a self-hosted host that still serves the routes, stays on its pin.
repin_langfuse_to_v3 = import_module(
    "products.warehouse_sources.backend.migrations.0184_repin_langfuse_api_version_v3"
).repin_langfuse_to_v3


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0204_externaldataschema_live_query_enabled")]

    operations = [
        # Reverse is a no-op: repinned rows are indistinguishable from natively created v3 rows, so a
        # blanket downgrade would clobber legitimate v3 pins.
        migrations.RunPython(repin_langfuse_to_v3, migrations.RunPython.noop, elidable=False),
    ]
