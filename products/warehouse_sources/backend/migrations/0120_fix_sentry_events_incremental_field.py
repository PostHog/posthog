from django.db import migrations

# The Sentry `issue_events` and `project_events` schemas fetch full event bodies (full=true),
# which carry a `dateReceived` timestamp rather than the `dateCreated` field the lightweight
# issue/event list serializers use. `dateCreated` was the only incremental field ever offered
# for these two schemas, so every incremental sync of them failed at cursor extraction with
# IncrementalFieldMissingFromDataError. Rewrite the stored config to the field Sentry actually
# returns for these endpoints.

AFFECTED_SCHEMA_NAMES = ("issue_events", "project_events")


def forwards(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # One row per configured Sentry table (thousands, not events-scale) — a per-row loop is fine.
    schemas = ExternalDataSchema.objects.filter(
        source__source_type="Sentry",
        deleted=False,
        name__in=AFFECTED_SCHEMA_NAMES,
        sync_type_config__incremental_field="dateCreated",
    ).iterator()

    for schema in schemas:
        schema.sync_type_config["incremental_field"] = "dateReceived"
        schema.save(update_fields=["sync_type_config"])


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0119_scaffold_motion_source")]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
