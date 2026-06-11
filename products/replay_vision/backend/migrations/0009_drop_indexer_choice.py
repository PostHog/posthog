from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0008_drop_indexer"),
    ]

    operations = [
        migrations.AlterField(
            model_name="replayscanner",
            name="scanner_type",
            field=models.CharField(
                choices=[
                    ("monitor", "Monitor"),
                    ("classifier", "Classifier"),
                    ("scorer", "Scorer"),
                    ("summarizer", "Summarizer"),
                ],
                max_length=32,
            ),
        ),
    ]
