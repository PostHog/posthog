from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_interviews", "0008_userinterview_user_interview_classif_gin"),
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
    ]
