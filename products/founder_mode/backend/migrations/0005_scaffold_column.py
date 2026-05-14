from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("founder_mode", "0004_backfill_current_step"),
    ]

    operations = [
        migrations.AddField(
            model_name="founderproject",
            name="scaffold",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
