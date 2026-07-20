from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0048_alter_visionaction_alert_config"),
    ]

    operations = [
        migrations.AlterField(
            model_name="replayscanner",
            name="model",
            field=models.CharField(
                choices=[
                    ("gemini-3-flash-preview", "Gemini 3 Flash"),
                    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
                ],
                max_length=64,
            ),
        ),
    ]
