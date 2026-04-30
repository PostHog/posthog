from django.db import migrations
from django.db.models import Case, IntegerField, Value, When


def copy_cache_age_to_data_freshness(apps, schema_editor):
    """
    Backfill data_freshness_seconds from cache_age_seconds, snapping each row to
    the nearest valid bucket from {900, 1800, 3600, 21600, 43200, 86400, 604800}.

    NULL rows are conservatively assigned 21600 (6h) — this minimizes silent
    staleness extension for pre-existing endpoints (the old code's interval-based
    default ranged from 2h to 12h depending on query kind).
    """
    EndpointVersion = apps.get_model("endpoints", "EndpointVersion")
    EndpointVersion.objects.update(
        data_freshness_seconds=Case(
            When(cache_age_seconds__isnull=True, then=Value(21600)),
            When(cache_age_seconds__lte=900, then=Value(900)),
            When(cache_age_seconds__lte=1800, then=Value(1800)),
            When(cache_age_seconds__lte=3600, then=Value(3600)),
            When(cache_age_seconds__lte=21600, then=Value(21600)),
            When(cache_age_seconds__lte=43200, then=Value(43200)),
            When(cache_age_seconds__lte=86400, then=Value(86400)),
            default=Value(604800),
            output_field=IntegerField(),
        )
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0026_add_data_freshness_seconds"),
    ]

    operations = [
        migrations.RunPython(copy_cache_age_to_data_freshness, noop),
    ]
