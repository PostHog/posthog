import django.db.models.fields.json
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0048_errortrackingsettings_linear_status_sync_enabled"),
        ("posthog", "1415_organizationaiterms"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingexternalreference",
            index=models.Index(
                models.F("integration_id"),
                django.db.models.fields.json.KeyTransform("id", "external_context"),
                name="et_extref_integration_ctx_id",
            ),
        ),
    ]
