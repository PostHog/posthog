import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0001_initial"),
        ("slack_app", "0009_slacksettings_ai_settings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="slacksettings",
            name="default_integration",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="slack_settings_as_default",
                to="posthog.integration",
            ),
        ),
    ]
