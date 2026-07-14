from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0044_replayscanner_feedback_themes"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayobservation",
            name="event_emitted_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the `$recording_observed` event was captured into the events table. Null on a succeeded row means emission never landed; the reconciler backfills those.",
                null=True,
            ),
        ),
    ]
