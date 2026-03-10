from django.db import migrations, models


def copy_cache_age_to_data_freshness(apps, schema_editor):
    EndpointVersion = apps.get_model("endpoints", "EndpointVersion")
    EndpointVersion.objects.filter(cache_age_seconds__isnull=False).update(
        data_freshness_seconds=models.F("cache_age_seconds")
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0021_add_data_freshness_seconds"),
    ]

    operations = [
        migrations.RunPython(copy_cache_age_to_data_freshness, noop),
    ]
