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
        # New default is `consider` ("All issues") — publish every validated finding. The AlterField
        # above only changes the default for future rows, so flip existing rows too (tiny table, and
        # the feature has no persisted rows yet). Reverse is a no-op: a hard reset can't restore the
        # prior per-row values.
        migrations.RunSQL(
            sql="UPDATE review_hog_reviewusersettings SET urgency_threshold = 'consider' "
            "WHERE urgency_threshold <> 'consider';",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
