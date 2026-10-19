from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0172_signalscoutconfig_precheck_disabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreportslackthread",
            name="kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("inbox_notification", "Inbox notification"),
                    ("scout_report", "Scout report"),
                    ("scout_report_note", "Scout report note"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="signalreportslackthread",
            name="target",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="signalreportslackthread",
            name="reply_ts",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
