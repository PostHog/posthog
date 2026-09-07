from django.conf import settings
from django.db import migrations
from django.utils import timezone

INTERNAL_TEAM_ID = 2  # PostHog's dogfooding team on US Cloud; the id means nothing on other instances.
_BATCH_SIZE = 2000


def reset_closed_beta_state(apps, schema_editor):
    # Cloud-only: launch pricing doesn't apply to self-hosted instances, so leave their scanners alone.
    deployment = (settings.CLOUD_DEPLOYMENT or "").upper()
    if deployment not in ("US", "EU"):
        return

    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")

    # Cutoff comes first so receipts written mid-migration by still-enabled scanners are never zeroed.
    cutoff = timezone.now()

    # Bulk update skips save() on purpose: no config change means no version bump, and the reconciler tears down schedules for disabled scanners.
    scanners = ReplayScanner.objects.filter(enabled=True)
    if deployment == "US":
        scanners = scanners.exclude(team_id=INTERNAL_TEAM_ID)
    scanners.update(enabled=False)

    # Zeroed receipts make the quota meter, usage reports, and quota limiting all read 0.
    while True:
        chunk = list(
            ReplayObservationUsage.objects.filter(credits__gt=0, created_at__lt=cutoff).values_list("pk", flat=True)[
                :_BATCH_SIZE
            ]
        )
        if not chunk:
            break
        ReplayObservationUsage.objects.filter(pk__in=chunk).update(credits=0)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0056_alter_replayobservation_help_texts"),
    ]

    operations = [
        migrations.RunPython(reset_closed_beta_state, migrations.RunPython.noop, elidable=True),
    ]
