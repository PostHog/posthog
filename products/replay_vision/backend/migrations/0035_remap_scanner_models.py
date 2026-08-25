from django.db import migrations

# Lite is retired from the lineup; existing Lite scanners move to the new cheap tier.
_MODEL_REMAP = {
    "gemini-3.1-flash-lite-preview": "gemini-2.5-flash",
}


def remap_scanner_models(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    for old, new in _MODEL_REMAP.items():
        ReplayScanner.objects.filter(model=old).update(model=new)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0034_alter_replayscanner_model"),
    ]

    operations = [
        migrations.RunPython(remap_scanner_models, migrations.RunPython.noop, elidable=True),
    ]
