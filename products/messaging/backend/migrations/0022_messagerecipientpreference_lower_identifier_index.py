import django.db.models.functions.text
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("messaging", "0021_provider_import_run_temporary_api_key"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="messagerecipientpreference",
            index=models.Index(
                models.F("team"),
                django.db.models.functions.text.Lower("identifier"),
                name="msg_pref_team_lower_ident",
            ),
        ),
    ]
