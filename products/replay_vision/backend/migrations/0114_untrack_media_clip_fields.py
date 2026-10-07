from django.db import migrations, models

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0113_drop_untracked_columns"),
    ]

    operations = [
        # The columns stay until a later migration drops them, so pods on the previous release can still select them.
        untrack_field("replayobservationmedia", "description", "video_end_ms", "rec_end_ms"),
        migrations.AlterField(
            model_name="replayobservationmedia",
            name="kind",
            field=models.CharField(choices=[("thumbnail", "Thumbnail"), ("chapter", "Chapter")], max_length=16),
        ),
    ]
