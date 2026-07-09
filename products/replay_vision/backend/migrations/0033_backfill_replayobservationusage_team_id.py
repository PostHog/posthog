from django.db import migrations
from django.db.models import OuterRef, Subquery

_BATCH_SIZE = 2000


def backfill_team_id(apps, schema_editor):
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")
    team_id_subquery = Subquery(ReplayObservation.objects.filter(pk=OuterRef("observation_id")).values("team_id")[:1])
    # Keyset-paginate by pk rather than re-querying team_id__isnull: an orphaned receipt (its observation
    # was deleted) resolves the subquery to NULL, so a shrinking-filter loop would never make progress on it.
    last_pk = None
    while True:
        rows = ReplayObservationUsage.objects.filter(team_id__isnull=True)
        if last_pk is not None:
            rows = rows.filter(pk__gt=last_pk)
        chunk = list(rows.order_by("pk").values_list("pk", flat=True)[:_BATCH_SIZE])
        if not chunk:
            break
        ReplayObservationUsage.objects.filter(pk__in=chunk).update(team_id=team_id_subquery)
        last_pk = chunk[-1]


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0032_replayobservationusage_rlou_created_team_idx"),
    ]

    operations = [
        migrations.RunPython(backfill_team_id, migrations.RunPython.noop, elidable=True),
    ]
