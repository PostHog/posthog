from django.db import migrations, models

import products.signals.backend.models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0175_signalteamconfig_agent_instructions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalscoutconfig",
            name="write_scopes",
            field=models.JSONField(
                db_default=[],
                default=products.signals.backend.models.default_scout_write_scopes,
            ),
        ),
    ]
