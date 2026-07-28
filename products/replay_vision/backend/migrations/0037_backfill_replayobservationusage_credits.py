from django.db import migrations
from django.db.models import OuterRef, Subquery
from django.db.models.fields.json import KeyTextTransform

# Frozen copy of billing.OBSERVATION_CREDITS_BY_MODEL at backfill time; the live table may change later.
_CREDITS_BY_MODEL = {
    "gemini-3-flash-preview": 5,
    "gemini-3.1-flash-lite-preview": 2,
}
_DEFAULT_CREDITS = 5
_BATCH_SIZE = 2000


def backfill_model_and_credits(apps, schema_editor):
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")

    # Model: keyset-paginate by pk. An orphaned receipt resolves the snapshot subquery to NULL, so a
    # shrinking model__isnull filter would loop forever on it; walking pk visits every row exactly once.
    # KeyTextTransform (->>), not scanner_snapshot__model (->): the latter stores the JSON-quoted value
    # ('"gemini-3-flash-preview"') into the text column, which then never matches the credit map.
    model_subquery = Subquery(
        ReplayObservation.objects.filter(pk=OuterRef("observation_id"))
        .annotate(_m=KeyTextTransform("model", "scanner_snapshot"))
        .values("_m")[:1]
    )
    last_pk = None
    while True:
        rows = ReplayObservationUsage.objects.filter(model__isnull=True)
        if last_pk is not None:
            rows = rows.filter(pk__gt=last_pk)
        chunk = list(rows.order_by("pk").values_list("pk", flat=True)[:_BATCH_SIZE])
        if not chunk:
            break
        ReplayObservationUsage.objects.filter(pk__in=chunk).update(model=model_subquery)
        last_pk = chunk[-1]

    # Credits: every pass sets a non-null value, so a shrinking credits__isnull filter terminates.
    def backfill_credits(credits, **extra_filter):
        while True:
            chunk = list(
                ReplayObservationUsage.objects.filter(credits__isnull=True, **extra_filter).values_list(
                    "pk", flat=True
                )[:_BATCH_SIZE]
            )
            if not chunk:
                break
            ReplayObservationUsage.objects.filter(pk__in=chunk).update(credits=credits)

    for model_id, credits in _CREDITS_BY_MODEL.items():
        backfill_credits(credits, model=model_id)
    # Orphaned receipts (observation deleted) and unknown models bill at the pre-differentiation baseline.
    backfill_credits(_DEFAULT_CREDITS)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0036_replayobservationusage_credits_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_model_and_credits, migrations.RunPython.noop, elidable=True),
    ]
