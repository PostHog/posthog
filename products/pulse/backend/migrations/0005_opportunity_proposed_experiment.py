from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pulse", "0004_briefconfig_goal_briefconfig_goal_metric_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunity",
            name="proposed_experiment",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
