from django.db import migrations, models

# Google retired gemini-2.5-flash: it 404s ("no longer available"), so every scanner still pinned
# to it fails its sweep. Move them to the current Flash tier — the same successor and default new
# scanners already get. The retired id stays priced in billing.OBSERVATION_CREDITS_BY_MODEL so
# frozen snapshots and in-flight receipts still bill correctly.
_MODEL_REMAP = {
    "gemini-2.5-flash": "gemini-3-flash-preview",
}


def remap_scanner_models(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    for old, new in _MODEL_REMAP.items():
        ReplayScanner.objects.filter(model=old).update(model=new)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0048_alter_visionaction_alert_config"),
    ]

    operations = [
        migrations.AlterField(
            model_name="replayscanner",
            name="model",
            field=models.CharField(
                choices=[
                    ("gemini-3-flash-preview", "Gemini 3 Flash"),
                    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
                ],
                max_length=64,
            ),
        ),
        migrations.RunPython(remap_scanner_models, migrations.RunPython.noop, elidable=True),
    ]
