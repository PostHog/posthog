from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0129_replayobservationmedia_small_asset"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservationmedia",
            index=models.Index(fields=["small_asset"], name="rom_small_asset_idx"),
        ),
    ]
