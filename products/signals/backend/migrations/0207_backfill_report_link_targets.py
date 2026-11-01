import json
import uuid

from django.db import migrations


def _link_target(content: str) -> str | None:
    """The canonical id of the report a `report_link` row names, or None when the row does not parse.

    The parsing is repeated here rather than taken from `ReportLink`, because what an applied
    migration did must not change when the live schema changes. A row that does not parse names no
    edge for any reader, so leaving it null loses nothing.
    """
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    try:
        return str(uuid.UUID(str(parsed.get("report_id"))))
    except ValueError:
        return None


def backfill_report_link_targets(apps, schema_editor):
    """Fill `link_target_id` on every `report_link` row written before the column existed.

    Reports link rarely, so the rows are few: one pass reads them all, and one UPDATE per target
    fills them.
    """
    SignalReportArtefact = apps.get_model("signals", "SignalReportArtefact")
    unfilled = SignalReportArtefact.objects.filter(type="report_link", link_target_id__isnull=True)
    ids_by_target: dict[str, list[uuid.UUID]] = {}
    for artefact_id, content in unfilled.values_list("id", "content").iterator(chunk_size=1000):
        target = _link_target(content)
        if target is not None:
            ids_by_target.setdefault(target, []).append(artefact_id)
    for target, ids in ids_by_target.items():
        # `update()`, not `save()`, so filling the column does not bump `updated_at`.
        unfilled.filter(id__in=ids).update(link_target_id=target)


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0206_signalreportartefact_link_target_index"),
    ]

    operations = [
        migrations.RunPython(backfill_report_link_targets, migrations.RunPython.noop),
    ]
