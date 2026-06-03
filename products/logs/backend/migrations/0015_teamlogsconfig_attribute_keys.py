from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


def backfill_singular_to_array(apps, schema_editor):
    """Carry each row's existing `logs_distinct_id_attribute_key` (singular) into
    `logs_distinct_id_attribute_keys` (a single-element list)."""
    Cfg = apps.get_model("logs", "TeamLogsConfig")
    for cfg in Cfg.objects.all():
        existing = cfg.logs_distinct_id_attribute_key or "posthogDistinctId"
        cfg.logs_distinct_id_attribute_keys = [existing]
        cfg.save(update_fields=["logs_distinct_id_attribute_keys"])


def rollback_array_to_singular(apps, schema_editor):
    Cfg = apps.get_model("logs", "TeamLogsConfig")
    for cfg in Cfg.objects.all():
        keys = cfg.logs_distinct_id_attribute_keys or ["posthogDistinctId"]
        cfg.logs_distinct_id_attribute_key = keys[0]
        cfg.save(update_fields=["logs_distinct_id_attribute_key"])


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0014_teamlogsconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamlogsconfig",
            name="logs_distinct_id_attribute_keys",
            field=ArrayField(
                base_field=models.CharField(max_length=200),
                default=list,
                size=None,
            ),
        ),
        migrations.RunPython(backfill_singular_to_array, rollback_array_to_singular, elidable=True),
        migrations.RemoveField(
            model_name="teamlogsconfig",
            name="logs_distinct_id_attribute_key",
        ),
    ]
