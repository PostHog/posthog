from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0010_backfill_change_kind_and_ssim"),
    ]

    operations = [
        migrations.AddField(
            model_name="run",
            name="is_partial",
            field=models.BooleanField(default=False),
        ),
    ]
