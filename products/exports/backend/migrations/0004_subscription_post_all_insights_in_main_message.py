from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0003_alter_subscription_target_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="post_all_insights_in_main_message",
            field=models.BooleanField(default=False),
        ),
    ]
