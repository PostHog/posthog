from django.db import migrations


class Migration(migrations.Migration):
    # A no-op: the drop could not take ACCESS EXCLUSIVE on posthog_user and posthog_organization within the lock budget in US.
    dependencies = [
        ("replay_vision", "0111_replayobservation_session_geoip"),
    ]

    operations: list = []
