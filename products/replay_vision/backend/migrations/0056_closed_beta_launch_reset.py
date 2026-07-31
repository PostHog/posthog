from datetime import UTC, datetime

from django.db import migrations
from django.utils import timezone

GRANT_AMOUNT = 10_000
GRANT_EXPIRES_AT = datetime(2026, 9, 1, tzinfo=UTC)
GRANT_REASON = "Replay Vision launch grant for closed-beta organizations"
INTERNAL_TEAM_ID = 2  # PostHog's own dogfooding team keeps its scanners running.
_BATCH_SIZE = 2000


def reset_closed_beta_state(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")
    ReplayQuotaGrant = apps.get_model("replay_vision", "ReplayQuotaGrant")

    # Snapshot the beta cohort before mutating anything; receipts cover orgs whose scanners were since deleted.
    beta_org_ids = set(ReplayScanner.objects.values_list("team__organization_id", flat=True).distinct()) | set(
        ReplayObservationUsage.objects.values_list("organization_id", flat=True).distinct()
    )

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

    # The reason doubles as an idempotency marker so bin/migrate retries can't double-grant.
    already_granted = set(
        ReplayQuotaGrant.objects.filter(reason=GRANT_REASON).values_list("organization_id", flat=True)
    )
    ReplayQuotaGrant.objects.bulk_create(
        ReplayQuotaGrant(
            organization_id=org_id,
            amount=GRANT_AMOUNT,
            expires_at=GRANT_EXPIRES_AT,
            reason=GRANT_REASON,
        )
        for org_id in sorted(beta_org_ids - already_granted, key=str)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0055_alter_replayscanner_model"),
    ]

    operations = [
        migrations.RunPython(reset_closed_beta_state, migrations.RunPython.noop, elidable=True),
    ]
