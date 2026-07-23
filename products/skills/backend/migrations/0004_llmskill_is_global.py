from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0003_backfill_scout_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="llmskill",
            name="is_global",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
