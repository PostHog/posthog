from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("warehouse_sources", "0193_externaldatasource_credentials_integration_id"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatasource",
            index=models.Index(
                condition=models.Q(credentials_integration_id__isnull=False),
                fields=["team", "credentials_integration_id"],
                name="eds_team_credentials_int_idx",
            ),
        ),
    ]
