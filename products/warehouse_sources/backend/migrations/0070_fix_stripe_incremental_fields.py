from django.db import migrations

# Stripe schemas ended up with broken `sync_type_config.incremental_field` values two ways:
# - API callers persisted the discovery display label "created_at" instead of the real field
#   "created" (every Stripe resource except InvoiceItem declares label=created_at, field=created),
# - migration 0794 blanket-set "created" on all Stripe append schemas, including InvoiceItem whose
#   only incremental field is "date".
# Both make every sync fail with a missing-column error at cursor extraction. Rewrite the config to
# the field the source actually declares; drop a stashed cursor value that can't serve as an epoch
# cursor under the corrected integer type so the next sync starts a clean pass.

INVOICE_ITEM_RESOURCE_NAME = "InvoiceItem"


def _fix(schema, field: str) -> None:
    schema.sync_type_config["incremental_field"] = field
    schema.sync_type_config["incremental_field_type"] = "integer"
    last_value = schema.sync_type_config.get("incremental_field_last_value")
    if last_value is not None and not isinstance(last_value, int | float):
        schema.sync_type_config["incremental_field_last_value"] = None
    schema.save(update_fields=["sync_type_config"])


def forwards(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # One row per configured Stripe table (thousands, not events-scale) — a per-row loop is fine.
    schemas = ExternalDataSchema.objects.filter(
        source__source_type="Stripe",
        deleted=False,
        sync_type_config__incremental_field__in=["created_at", "created"],
    ).iterator()

    for schema in schemas:
        incremental_field = schema.sync_type_config.get("incremental_field")
        if schema.name == INVOICE_ITEM_RESOURCE_NAME:
            _fix(schema, "date")
        elif incremental_field == "created_at":
            _fix(schema, "created")
        # `created` on any other resource is the declared field — leave it alone.


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0069_alter_externaldatasource_created_via")]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
