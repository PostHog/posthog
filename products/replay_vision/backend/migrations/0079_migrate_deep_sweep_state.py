import datetime as dt

from django.db import migrations


def copy_watermark_into_state(apps, schema_editor):
    """Carry each scanner's deep watermark into the new state object.

    Without this every scanner reads as never deep-swept, and the seeding branch would restart each
    one at its current fast watermark, silently dropping the catch-up range behind it.
    """
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    rows = []
    for scanner in ReplayScanner.objects.exclude(last_deep_swept_at=None).only("id", "last_deep_swept_at").iterator():
        scanner.deep_sweep_state = {
            "swept_through": scanner.last_deep_swept_at.isoformat(),
            "seen_session_id": "",
            "attempted_at": None,
        }
        rows.append(scanner)
        if len(rows) >= 500:
            ReplayScanner.objects.bulk_update(rows, ["deep_sweep_state"])
            rows = []
    if rows:
        ReplayScanner.objects.bulk_update(rows, ["deep_sweep_state"])


def copy_state_back_into_watermark(apps, schema_editor):
    """Put the position back where the reverted code reads it.

    Scanners created after this migration have no `last_deep_swept_at` at all, so simply clearing the
    state would leave them looking never-swept and drop their whole catch-up backlog.
    """
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    rows = []
    for scanner in ReplayScanner.objects.exclude(deep_sweep_state=None).only("id", "deep_sweep_state").iterator():
        swept_through = (scanner.deep_sweep_state or {}).get("swept_through")
        if not isinstance(swept_through, str):
            continue
        try:
            parsed = dt.datetime.fromisoformat(swept_through)
        except ValueError:
            continue
        scanner.last_deep_swept_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
        scanner.deep_sweep_state = None
        rows.append(scanner)
        if len(rows) >= 500:
            ReplayScanner.objects.bulk_update(rows, ["last_deep_swept_at", "deep_sweep_state"])
            rows = []
    if rows:
        ReplayScanner.objects.bulk_update(rows, ["last_deep_swept_at", "deep_sweep_state"])


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0078_replayscanner_deep_sweep_state_and_more"),
    ]

    operations = [
        migrations.RunPython(copy_watermark_into_state, copy_state_back_into_watermark),
        # State only: the column stays so the currently deployed workers, which still select it, keep
        # working through the rollout. Dropping it is a separate change after a full deploy cycle.
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="replayscanner", name="last_deep_swept_at")],
            database_operations=[],
        ),
    ]
