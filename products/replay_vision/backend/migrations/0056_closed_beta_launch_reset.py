from django.db import migrations
from django.utils import timezone

INTERNAL_TEAM_ID = 2  # PostHog's own dogfooding team keeps its scanners running.
_BATCH_SIZE = 2000


def reset_closed_beta_state(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")

    # Bulk update skips save() on purpose: no config change means no version bump, and the reconciler tears down schedules for disabled scanners.
    ReplayScanner.objects.filter(enabled=True).exclude(team_id=INTERNAL_TEAM_ID).update(enabled=False)

    # Zeroed receipts make the quota meter, usage reports, and quota limiting all read 0; the cutoff protects receipts written concurrently by still-enabled scanners.
    cutoff = timezone.now()
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
        ("replay_vision", "0055_alter_replayscanner_model"),
    ]

    operations = [
        migrations.RunPython(reset_closed_beta_state, migrations.RunPython.noop, elidable=True),
    ]
