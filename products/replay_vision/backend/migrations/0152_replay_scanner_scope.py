from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0151_backfill_replayscanner_sweep_cadence"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayscanner",
            name="scope",
            field=models.JSONField(
                blank=True,
                help_text='Which sessions the scanner watches and the label it gives each one, as `{"kind": ...}`.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="replayobservation",
            name="group_key",
            field=models.CharField(
                blank=True,
                help_text="The label the scanner's scope gave this session, such as an experiment variant. Null when the scope gives none.",
                max_length=400,
                null=True,
            ),
        ),
    ]
