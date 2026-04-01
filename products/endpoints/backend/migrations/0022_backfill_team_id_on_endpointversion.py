from django.core.paginator import Paginator
from django.db import migrations, models


def backfill_team(apps, schema_editor):
    Endpoint = apps.get_model("endpoints", "Endpoint")
    EndpointVersion = apps.get_model("endpoints", "EndpointVersion")

    versions = EndpointVersion.objects.filter(team_id__isnull=True).order_by("id")
    paginator = Paginator(versions, 500)

    for page_number in paginator.page_range:
        page = paginator.page(page_number)
        ids = [obj.id for obj in page.object_list]

        EndpointVersion.objects.filter(id__in=ids).update(
            team_id=models.Subquery(Endpoint.objects.filter(pk=models.OuterRef("endpoint_id")).values("team_id")[:1])
        )


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0021_add_team_to_endpointversion"),
    ]

    operations = [
        migrations.RunPython(backfill_team, migrations.RunPython.noop),
    ]
