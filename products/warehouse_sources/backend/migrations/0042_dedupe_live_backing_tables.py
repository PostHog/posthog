from django.db import migrations
from django.db.models import Count
from django.utils import timezone


def dedupe_live_backing_tables(apps, schema_editor):
    # Keep the newest live self-managed backing table per (team, name); soft-delete the rest so the
    # partial unique index added next can be built.
    DataWarehouseTable = apps.get_model("warehouse_sources", "DataWarehouseTable")

    live = DataWarehouseTable.objects.filter(external_data_source__isnull=True).exclude(deleted=True)
    duplicate_groups = live.values("team_id", "name").annotate(n=Count("id")).filter(n__gt=1)

    now = timezone.now()
    for group in duplicate_groups.iterator():
        rows = list(live.filter(team_id=group["team_id"], name=group["name"]).order_by("-created_at", "-id"))
        for old_table in rows[1:]:
            old_table.deleted = True
            old_table.deleted_at = now
            old_table.save(update_fields=["deleted", "deleted_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0041_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        migrations.RunPython(dedupe_live_backing_tables, migrations.RunPython.noop),
    ]
