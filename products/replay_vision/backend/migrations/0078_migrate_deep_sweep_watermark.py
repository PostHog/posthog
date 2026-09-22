from django.db import migrations
from django.db.models import F


def copy_watermark_into_deep_fields(apps, schema_editor):
    """Seed the new columns so no scanner reads as never deep-swept.

    `deep_attempted_at` is seeded too: the settled-since-last-edit check compares `updated_at` against
    it, and leaving it null would send every no-event-filter scanner through one full-width deep query
    it used to skip.
    """
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayScanner.objects.exclude(last_deep_swept_at=None).update(
        deep_swept_through=F("last_deep_swept_at"),
        deep_attempted_at=F("last_deep_swept_at"),
    )


def copy_watermark_back(apps, schema_editor):
    """Put the position back where reverted code reads it, covering scanners created after this migration."""
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayScanner.objects.exclude(deep_swept_through=None).update(last_deep_swept_at=F("deep_swept_through"))


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0077_replayscanner_deep_sweep_fields"),
    ]

    operations = [
        migrations.RunPython(copy_watermark_into_deep_fields, copy_watermark_back),
        # State only: the column stays so the currently deployed workers, which still select it, keep
        # working through the rollout. Dropping it is a separate change after a full deploy cycle.
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="replayscanner", name="last_deep_swept_at")],
            database_operations=[],
        ),
    ]
