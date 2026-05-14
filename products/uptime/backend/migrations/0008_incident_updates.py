from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("uptime", "0007_monitor_mode_alter_monitor_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="incident",
            name="updates",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
