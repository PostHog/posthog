from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="delivery_config",
            field=models.JSONField(default=dict),
        ),
    ]
