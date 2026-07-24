from datetime import UTC, datetime

from django.db import migrations

from dateutil.relativedelta import relativedelta

from posthog.date_util import start_of_month

_BATCH = 1000


def backfill_current_period(apps, schema_editor):
    """Seed receipts for the current month's already-succeeded observations (idempotent via ignore_conflicts)."""
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")

    now = datetime.now(UTC)
    period_start = start_of_month(now)  # same window helper compute_quota_snapshot reads with
    period_end = period_start + relativedelta(months=1)

    rows = (
        ReplayObservation.objects.filter(
            status="succeeded",
            created_at__gte=period_start,
            created_at__lt=period_end,
        )
        .values_list("id", "team__organization_id", "created_at")
        .iterator(chunk_size=_BATCH)  # stream the read; the whole succeeded-set could be large across orgs
    )

    ReplayObservationUsage.objects.bulk_create(
        (
            ReplayObservationUsage(
                observation_id=obs_id,
                organization_id=org_id,
                observation_created_at=created_at,
                created_at=now,
            )
            for obs_id, org_id, created_at in rows
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
