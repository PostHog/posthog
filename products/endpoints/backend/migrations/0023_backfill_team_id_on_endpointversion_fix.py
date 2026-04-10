from django.db import migrations, models


def backfill_team(apps, schema_editor):
    Endpoint = apps.get_model("endpoints", "Endpoint")
    EndpointVersion = apps.get_model("endpoints", "EndpointVersion")

    all_ids = list(EndpointVersion.objects.filter(team_id__isnull=True).order_by("id").values_list("id", flat=True))

    for i in range(0, len(all_ids), 500):
        batch = all_ids[i : i + 500]
        EndpointVersion.objects.filter(id__in=batch).update(
            team_id=models.Subquery(Endpoint.objects.filter(pk=models.OuterRef("endpoint_id")).values("team_id")[:1])
        )


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0022_backfill_team_id_on_endpointversion"),
    ]

    operations = [
        migrations.RunPython(backfill_team, migrations.RunPython.noop),
    ]
