from django.db import migrations
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Exists, IntegerField, OuterRef
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

PREVIEW = "gemini-3-flash-preview"
REMAPPED_TARGET = "gemini-3.6-flash"
LEGACY_FLASH = "gemini-3.5-flash"


def _remap_applied_at(connection):
    row = (
        MigrationRecorder(connection).migration_qs.filter(app="replay_vision", name="0052_remap_scanner_models").first()
    )
    return row.applied if row else None


def _do_revert(apps, remapped_at):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")

    # A scanner on 3.6-flash created before 0052 ran was necessarily remapped there: 3.6-flash only
    # became selectable in the same deploy, so before it the scanner was on preview or 3.5-flash.
    # Revert those to the 5-credit preview default, except the ones we can positively see were on the
    # 15-credit 3.5-flash tier (a snapshot at their current version recorded 3.5-flash). Scanners
    # created after the remap were never touched by it, so they keep whatever they chose.
    was_legacy_flash = (
        ReplayObservation.objects.filter(scanner_id=OuterRef("pk"), scanner_snapshot__model=LEGACY_FLASH)
        .annotate(snap_version=Cast(KeyTextTransform("scanner_version", "scanner_snapshot"), IntegerField()))
        .filter(snap_version=OuterRef("scanner_version"))
    )
    ReplayScanner.objects.filter(model=REMAPPED_TARGET, created_at__lt=remapped_at).exclude(
        Exists(was_legacy_flash)
    ).update(model=PREVIEW)


def revert_remapped_preview_scanners(apps, schema_editor):
    remapped_at = _remap_applied_at(schema_editor.connection)
    if remapped_at is None:
        return  # 0052 never ran here (fresh install): nothing was remapped.
    _do_revert(apps, remapped_at)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0053_alter_replayscanner_model"),
    ]

    operations = [
        migrations.RunPython(revert_remapped_preview_scanners, migrations.RunPython.noop, elidable=True),
    ]
