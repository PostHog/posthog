from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0141_signalscoutemission_weight_nullable"),
    ]

    operations = [
        # Phase 2: the field leaves model state while the column stays, so a pod on either release
        # can still write an emission row. The column drop follows one deploy cycle later.
        untrack_field("signalscoutemission", "weight"),
    ]
