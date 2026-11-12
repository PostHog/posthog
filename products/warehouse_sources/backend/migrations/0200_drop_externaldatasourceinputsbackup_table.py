from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    # 0199 removed the model from state. The table has no foreign keys.
    dependencies = [
        ("warehouse_sources", "0199_remove_externaldatasourceinputsbackup_state"),
    ]

    operations = [
        SafeDropTable("warehouse_sources_externaldatasourceinputsbackup"),
    ]
