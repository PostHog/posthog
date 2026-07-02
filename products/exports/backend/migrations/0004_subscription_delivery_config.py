from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0003_alter_subscription_target_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="delivery_config",
            field=models.JSONField(default=dict),
        ),
    ]
