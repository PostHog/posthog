from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0184_signalscratchpad_search_trgm_indexes")]

    operations = [
        migrations.AddField(
            model_name="signalteamconfig",
            name="onboarding",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
