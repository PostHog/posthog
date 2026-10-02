from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0011_generic_job_tables"),
    ]

    # 0007 took the duckgres sink models out of Django state and kept their tables.
    # SafeDropTable refuses partitioned tables, so 0013 drops sourcebatchduckgresstatus.
    operations = [
        SafeDropTable(["sourcebatchduckgresapply", "sourceduckgresgrouplease"]),
    ]
