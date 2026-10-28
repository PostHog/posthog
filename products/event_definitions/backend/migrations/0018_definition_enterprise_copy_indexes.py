from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [("event_definitions", "0017_propertydefinition_enterprise_copies")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                condition=models.Q(("base_owner__isnull", False)),
                fields=["base_owner"],
                name="posthog_eventdef_owner_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                condition=models.Q(("base_updated_by__isnull", False)),
                fields=["base_updated_by"],
                name="posthog_eventdef_upd_by_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                condition=models.Q(("base_verified_by__isnull", False)),
                fields=["base_verified_by"],
                name="posthog_eventdef_ver_by_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="propertydefinition",
            index=models.Index(
                condition=models.Q(("base_updated_by__isnull", False)),
                fields=["base_updated_by"],
                name="posthog_propdef_upd_by_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="propertydefinition",
            index=models.Index(
                condition=models.Q(("base_verified_by__isnull", False)),
                fields=["base_verified_by"],
                name="posthog_propdef_ver_by_idx",
            ),
        ),
    ]
