# Generated manually — adds denormalized team_id to child models
# and run purpose/review_decision fields.

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
        migrations.AddField(
            model_name="run",
            name="purpose",
            field=models.CharField(
                max_length=20,
                choices=[("review", "review"), ("observe", "observe")],
                default="review",
            ),
        ),
        migrations.AddField(
            model_name="run",
            name="review_decision",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("pending", "pending"),
                    ("human_approved", "human_approved"),
                    ("auto_approved", "auto_approved"),
                    ("agent_approved", "agent_approved"),
                    ("rejected", "rejected"),
                ],
                default="pending",
            ),
        ),
    ]
