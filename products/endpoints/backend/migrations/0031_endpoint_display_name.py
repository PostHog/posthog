from django.db import migrations, models


def backfill_display_name(apps, schema_editor):
    Endpoint = apps.get_model("endpoints", "Endpoint")
    Endpoint.objects.filter(display_name="").update(display_name=models.F("name"))


def reverse_backfill_display_name(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0030_endpointversion_last_executed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpoint",
            name="display_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Human-readable display name. The URL-safe slug is stored in `name`.",
                max_length=255,
            ),
        ),
        migrations.RunPython(backfill_display_name, reverse_backfill_display_name),
    ]
