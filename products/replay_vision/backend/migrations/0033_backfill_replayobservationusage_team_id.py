from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill_team_id(apps, schema_editor):
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")
    ReplayObservationUsage = apps.get_model("replay_vision", "ReplayObservationUsage")
    ReplayObservationUsage.objects.filter(team_id__isnull=True).update(
        team_id=Subquery(ReplayObservation.objects.filter(pk=OuterRef("observation_id")).values("team_id")[:1])
    )


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0032_replayobservationusage_rlou_created_team_idx"),
    ]

    operations = [
        migrations.RunPython(backfill_team_id, migrations.RunPython.noop, elidable=True),
    ]
