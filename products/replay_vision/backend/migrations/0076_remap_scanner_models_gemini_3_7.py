from django.db import migrations

# 3.7 Flash supersedes 3.6 Flash at identical list prices (same 15-credit charge), so existing
# premium scanners move over. Frozen observation snapshots keep the old id.
_MODEL_REMAP = {
    "gemini-3.6-flash": "gemini-3.7-flash",
}


def remap_scanner_models(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    for old, new in _MODEL_REMAP.items():
        ReplayScanner.objects.filter(model=old).update(model=new)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0075_alter_replayscanner_model"),
    ]

    operations = [
        migrations.RunPython(remap_scanner_models, migrations.RunPython.noop, elidable=True),
    ]
