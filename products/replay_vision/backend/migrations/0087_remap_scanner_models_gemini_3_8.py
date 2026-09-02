from django.db import migrations


# 3.8 Flash supersedes 3.7 Flash at identical list prices (same 15-credit charge), so existing
# premium scanners move over. Frozen observation snapshots keep the old id.
def remap_scanner_models(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayScanner.objects.filter(model="gemini-3.7-flash").update(model="gemini-3.8-flash")


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0086_remove_visionactionrun_vision_action_and_more"),
    ]

    operations = [
        migrations.RunPython(remap_scanner_models, migrations.RunPython.noop, elidable=True),
    ]
