from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("review_hog", "0016_reviewreport_reviewhog_rpt_team_recent_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reviewusersettings",
            name="urgency_threshold",
            field=models.CharField(
                choices=[
                    ("consider", "Consider"),
                    ("should_fix", "Should Fix"),
                    ("must_fix", "Must Fix"),
                ],
                db_default="consider",
                default="consider",
                max_length=20,
            ),
        ),
    ]
