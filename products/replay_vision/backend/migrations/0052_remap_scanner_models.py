from django.db import migrations

# Superseded models move to their tier's successor (2.5 Flash is shut down by Google on 2026-10-16,
# the other two are replaced by 3.6 Flash). Frozen observation snapshots keep the old ids.
_MODEL_REMAP = {
    "gemini-2.5-flash": "gemini-3.5-flash-lite",
    "gemini-3-flash-preview": "gemini-3.6-flash",
    "gemini-3.5-flash": "gemini-3.6-flash",
}


def remap_scanner_models(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    for old, new in _MODEL_REMAP.items():
        ReplayScanner.objects.filter(model=old).update(model=new)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0051_alter_replayscanner_model"),
    ]

    operations = [
        migrations.RunPython(remap_scanner_models, migrations.RunPython.noop, elidable=True),
    ]
