from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_interviews", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userinterview",
            name="respondent_name",
            field=models.CharField(blank=True, db_default="", default="", max_length=400),
        ),
        migrations.AddField(
            model_name="userinterview",
            name="respondent_key",
            field=models.CharField(blank=True, db_default="", default="", max_length=64),
        ),
        migrations.AddField(
            model_name="userinterview",
            name="distinct_id",
            field=models.CharField(blank=True, db_default="", default="", max_length=200),
        ),
    ]
