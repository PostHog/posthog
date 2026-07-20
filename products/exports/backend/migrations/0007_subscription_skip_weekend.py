from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0006_subscription_ai_query_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="skip_weekend",
            field=models.BooleanField(default=False),
        ),
    ]
