from django.db import migrations

# The Plausible `pages`, `entry_pages`, and `exit_pages` breakdowns gained a hostname dimension,
# which widens their composite primary key. Existing schemas are stuck on the old key two ways:
# `resolve_primary_keys` gives the persisted `sync_type_config["primary_key_columns"]` absolute
# precedence over the source's keys, and existing Delta rows carry no hostname column, so a merge
# on the widened key would leave old hostname-less rows beside the new per-hostname rows and
# double-count. Rewrite the persisted key to the widened one and stamp `reset_pipeline`, so the
# next scheduled sync wipes the table and rebuilds it keyed on hostname
# (`handle_reset_or_full_refresh`).

AFFECTED_PRIMARY_KEYS = {
    "pages": (["date", "page"], ["date", "page", "hostname"]),
    "entry_pages": (["date", "entry_page"], ["date", "entry_page", "entry_page_hostname"]),
    "exit_pages": (["date", "exit_page"], ["date", "exit_page", "exit_page_hostname"]),
}


def forwards(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # One row per configured Plausible page table (the source is Alpha) — a per-row loop is fine.
    schemas = ExternalDataSchema.objects.filter(
        source__source_type="Plausible",
        deleted=False,
        name__in=AFFECTED_PRIMARY_KEYS.keys(),
    ).iterator()

    for schema in schemas:
        config = schema.sync_type_config or {}
        stale_key, widened_key = AFFECTED_PRIMARY_KEYS[schema.name]
        # Only replace the exact stale key. A different persisted value is a deliberate user
        # override, which the reset below rebuilds the table under unchanged.
        if config.get("primary_key_columns") == stale_key:
            config["primary_key_columns"] = widened_key
        # Stamp every affected schema, keyed or not: a schema without a persisted key still holds
        # hostname-less rows the merge can never update or delete. Full-refresh schemas wipe on
        # every run anyway, so the stamp is a no-op difference there.
        config["reset_pipeline"] = True
        schema.sync_type_config = config
        schema.save(update_fields=["sync_type_config"])


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0156_externaldatajob_pipeline_status_finished_idx")]

    operations = [
        # Reverse is a no-op: the reset consumes itself on the next sync, and restoring the stale
        # narrow key would recreate the subdomain collision this repairs.
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
