from datetime import UTC, datetime

from django.db import migrations

from dateutil.relativedelta import relativedelta

from posthog.date_util import start_of_month
from posthog.migration_helpers import chunked_queryset_iterator

_BATCH = 1000


def backfill_current_period(apps, schema_editor):
    """Seed receipts for the current month's already-succeeded observations (idempotent via ignore_conflicts)."""
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")

    now = datetime.now(UTC)
    period_start = start_of_month(now)  # same window helper compute_quota_snapshot reads with
    period_end = period_start + relativedelta(months=1)

    # stream the read via keyset pagination; the whole succeeded-set could be large across orgs
    observations = ReplayObservation.objects.filter(
        status="succeeded",
        created_at__gte=period_start,
        created_at__lt=period_end,
    ).select_related("team")

    ReplayObservationUsage.objects.bulk_create(
        (
            ReplayObservationUsage(
                observation_id=obs.id,
                organization_id=obs.team.organization_id,
                observation_created_at=obs.created_at,
                created_at=now,
            )
            for obs in chunked_queryset_iterator(observations, chunk_size=_BATCH)
        ),
        ignore_conflicts=True,
        batch_size=_BATCH,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0017_replayobservationusage"),
    ]

    operations = [
        migrations.RunPython(backfill_current_period, migrations.RunPython.noop),
    ]
