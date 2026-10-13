from typing import Any

from django.db import migrations


def nest_key_file_under_auth_type(job_inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Move a BigQuery source's flat `key_file` under the `auth_type` selection, or None if it is
    already migrated."""
    if "auth_type" in job_inputs:
        return None

    migrated = dict(job_inputs)
    key_file = migrated.pop("key_file", None)
    migrated["auth_type"] = {
        "selection": "key_file",
        "key_file": key_file if isinstance(key_file, dict) else {},
    }
    return migrated


def flatten_auth_type_to_key_file(job_inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Undo `nest_key_file_under_auth_type`, or None if there is nothing to undo.

    A source set up on a service account integration has no key file to restore, so it comes back
    with only the integration id, which the pre-migration code ignores. Reversing is a rollback
    path: such a source has to be reconnected rather than silently syncing on a stale key.
    """
    auth_type = job_inputs.get("auth_type")
    if not isinstance(auth_type, dict):
        return None

    flattened = dict(job_inputs)
    flattened.pop("auth_type")

    key_file = auth_type.get("key_file")
    if isinstance(key_file, dict):
        flattened["key_file"] = key_file

    integration_id = auth_type.get("google_cloud_service_account_integration_id")
    if integration_id not in (None, ""):
        flattened["google_cloud_service_account_integration_id"] = integration_id

    return flattened


def _rewrite_bigquery_job_inputs(apps, rewrite):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="BigQuery").iterator():
        if not isinstance(source.job_inputs, dict):
            continue

        rewritten = rewrite(source.job_inputs)
        if rewritten is None:
            continue

        source.job_inputs = rewritten
        source.save(update_fields=["job_inputs"])


def migrate_bigquery_job_inputs(apps, schema_editor):
    _rewrite_bigquery_job_inputs(apps, nest_key_file_under_auth_type)


def reverse_migrate_bigquery_job_inputs(apps, schema_editor):
    _rewrite_bigquery_job_inputs(apps, flatten_auth_type_to_key_file)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0164_repin_factorial_api_version"),
    ]

    operations = [
        migrations.RunPython(migrate_bigquery_job_inputs, reverse_migrate_bigquery_job_inputs),
    ]
