from django.db import migrations, models


def backfill_display_name(apps, schema_editor):
    Endpoint = apps.get_model("endpoints", "Endpoint")
    Endpoint.objects.filter(display_name="").update(display_name=models.F("name"))


def reverse_backfill_display_name(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0031_endpoint_display_name"),
    ]

    operations = [
        migrations.RunPython(backfill_display_name, reverse_backfill_display_name),
    ]
