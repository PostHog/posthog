from django.db import migrations


# 3.8 Flash supersedes 3.7 Flash at identical list prices (same 15-credit charge), so existing
# premium scanners move over. Frozen observation snapshots keep the old id, and `update()` leaves
# `scanner_version` alone on purpose: an equal-price swap should not invalidate pinned estimates.
def remap_scanner_models(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayScanner.objects.filter(model="gemini-3.7-flash").update(model="gemini-3.8-flash")


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0087_replayscanner_estimate_attempted_at"),
    ]

    operations = [
        migrations.RunPython(remap_scanner_models, migrations.RunPython.noop, elidable=True),
    ]
