from django.db import migrations
from django.db.models import OuterRef, Subquery

# Frozen copy of billing.OBSERVATION_CREDITS_BY_MODEL at backfill time; the live table may change later.
_CREDITS_BY_MODEL = {
    "gemini-3-flash-preview": 5,
    "gemini-3.1-flash-lite-preview": 2,
}
_DEFAULT_CREDITS = 5


def backfill_model_and_credits(apps, schema_editor):
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")
    ReplayObservationUsage.objects.filter(model__isnull=True).update(
        model=Subquery(
            ReplayObservation.objects.filter(pk=OuterRef("observation_id")).values("scanner_snapshot__model")[:1]
        )
    )
    for model_id, credits in _CREDITS_BY_MODEL.items():
        ReplayObservationUsage.objects.filter(credits__isnull=True, model=model_id).update(credits=credits)
    # Orphaned receipts (observation deleted) and unknown models bill at the pre-differentiation baseline.
    ReplayObservationUsage.objects.filter(credits__isnull=True).update(credits=_DEFAULT_CREDITS)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0034_replayobservationusage_credits_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_model_and_credits, migrations.RunPython.noop, elidable=True),
    ]
