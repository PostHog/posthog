from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0151_scout_config_retired_pause_reason")]

    operations = [
        # Choices only: `status` stays a CharField of the same length, so this emits no SQL.
        migrations.AlterField(
            model_name="signalscoutsuggestionset",
            name="status",
            field=models.CharField(
                choices=[
                    ("fresh", "Fresh"),
                    ("stale", "Stale"),
                    ("failed", "Failed"),
                    ("empty", "Empty"),
                    ("low_activity", "Low activity"),
                ],
                db_default="empty",
                default="empty",
                max_length=16,
            ),
        ),
    ]
