from django.db import migrations
from django.db.models import Count, Q


def check_for_duplicate_active_names(apps, schema_editor) -> None:
    """Fail with an actionable message before the index rebuild starts.

    The unique index can be invalid, so duplicate active names can exist.
    A failed rebuild reports only one duplicate, so list them all here.
    """
    Endpoint = apps.get_model("endpoints", "Endpoint")
    duplicates = (
        Endpoint.objects.filter(Q(deleted=False) | Q(deleted__isnull=True))
        .values("team_id", "name")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
        .order_by("team_id", "name")
    )
    if not duplicates:
        return
    detail = "; ".join(f"team_id={row['team_id']} name={row['name']!r} rows={row['row_count']}" for row in duplicates)
    raise RuntimeError(
        "Cannot rebuild team_id_endpoint_name_active: several active endpoints share a name "
        "in the same team. Soft-delete or rename the extra rows, then run this migration again. "
        f"Duplicates: {detail}"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0031_endpointversion_optional_breakdown_properties"),
    ]

    operations = [
        migrations.RunPython(check_for_duplicate_active_names, migrations.RunPython.noop),
    ]
