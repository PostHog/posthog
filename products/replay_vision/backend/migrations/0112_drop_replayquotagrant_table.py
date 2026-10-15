from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    # 0058 removed ReplayQuotaGrant from state only, so its deferred foreign keys to posthog_organization and
    # posthog_user stayed. Django no longer cascades into the table, so deleting an organization or user that
    # a grant row references fails at COMMIT until the table is gone.
    dependencies = [
        ("replay_vision", "0111_replayobservation_session_geoip"),
    ]

    operations = [
        SafeDropTable("replay_vision_replayquotagrant"),
    ]
