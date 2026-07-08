from django.db import migrations
from django.db.models import F

# Grants were denominated in observations; credits are 5 per baseline observation.
_CREDITS_PER_LEGACY_OBSERVATION = 5


def redenominate_grants(apps, schema_editor):
    ReplayQuotaGrant = apps.get_model("replay_vision", "ReplayQuotaGrant")
    ReplayQuotaGrant.objects.update(amount=F("amount") * _CREDITS_PER_LEGACY_OBSERVATION)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0035_backfill_replayobservationusage_credits"),
    ]

    operations = [
        migrations.RunPython(redenominate_grants, migrations.RunPython.noop, elidable=True),
    ]
