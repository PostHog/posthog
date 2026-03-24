# Generated manually — adds denormalized team_id to child models.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifact",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="run",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="runsnapshot",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
    ]
