import json

from django.db import migrations

_BATCH_SIZE = 2000
_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


def _rank_from_content(content: str) -> int | None:
    """Mirror of the DB trigger's derivation, tolerant of malformed/legacy JSON (-> None)."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return _PRIORITY_RANK.get(data.get("priority"))


def backfill(apps, schema_editor):
    # Existing priority_judgment rows predate the trigger (0051), so their priority_rank is NULL.
    # Fill it in keyset batches (id-ordered) so each UPDATE is short and commits independently
    # (migration is atomic=False). Updating only priority_rank does not fire the `OF content, type`
    # trigger, so our computed value lands directly. New writes from 0051 onward are already maintained.
    SignalReportArtefact = apps.get_model("signals", "SignalReportArtefact")
    base = SignalReportArtefact.objects.filter(type="priority_judgment").order_by("id")
    last_id = None
    while True:
        batch_qs = base if last_id is None else base.filter(id__gt=last_id)
        rows = list(batch_qs.values_list("id", "content")[:_BATCH_SIZE])
        if not rows:
            break
        to_update = []
        for row_id, content in rows:
            obj = SignalReportArtefact(id=row_id, priority_rank=_rank_from_content(content))
            to_update.append(obj)
        SignalReportArtefact.objects.bulk_update(to_update, ["priority_rank"], batch_size=_BATCH_SIZE)
        last_id = rows[-1][0]


class Migration(migrations.Migration):
    atomic = False  # batch commits independently; backfill must not run as one giant transaction

    dependencies = [
        ("signals", "0051_signalreportartefact_priority_rank_trigger"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop, elidable=True),
    ]
