from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0004_logsalertevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="logsalertevent",
            name="kind",
            field=models.CharField(
                choices=[
                    ("check", "Check"),
                    ("reset", "Reset"),
                    ("enable", "Enable"),
                    ("disable", "Disable"),
                    ("snooze", "Snooze"),
                    ("unsnooze", "Unsnooze"),
                    ("threshold_change", "Threshold change"),
                ],
                default="check",
                max_length=32,
            ),
        ),
    ]
