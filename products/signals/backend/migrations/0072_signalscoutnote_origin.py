from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0071_signalscoutnote"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscoutnote",
            name="origin",
            field=models.CharField(
                choices=[("human", "Left directly"), ("report_dismissal", "Derived from inbox dismissal feedback")],
                db_default="human",
                default="human",
                max_length=32,
            ),
        ),
    ]
