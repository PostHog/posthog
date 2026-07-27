from django.db import migrations


def delete_indexer_scanners(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayScanner.objects.filter(scanner_type="indexer").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0007_add_ineligible_status"),
    ]

    operations = [
        migrations.RunPython(delete_indexer_scanners, reverse_code=migrations.RunPython.noop),
    ]
