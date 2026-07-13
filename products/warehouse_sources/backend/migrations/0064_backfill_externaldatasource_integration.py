from django.db import migrations

BATCH_SIZE = 500

# Snapshot of integration_id_from_job_inputs from models/external_data_source.py —
# migrations must stay self-contained as live code evolves.
_NON_POSTHOG_INTEGRATION_JOB_INPUT_KEYS = frozenset({"auth_oauth2_integration_id"})


def _integration_id_from_job_inputs(job_inputs):
    if not isinstance(job_inputs, dict):
        return None
    for key in sorted(job_inputs):
        if not key.endswith("_integration_id") or key in _NON_POSTHOG_INTEGRATION_JOB_INPUT_KEYS:
            continue
        try:
            return int(str(job_inputs[key]))
        except (TypeError, ValueError):
            continue
    return None


def backfill(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    Integration = apps.get_model("posthog", "Integration")

    pending = []

    def flush():
        if not pending:
            return
        referenced_ids = {integration_id for _, _, integration_id in pending}
        # Only link integrations that exist in the source's team — job_inputs is user-controlled.
        team_by_integration = dict(Integration.objects.filter(id__in=referenced_ids).values_list("id", "team_id"))
        updates = [
            ExternalDataSource(id=source_id, integration_id=integration_id)
            for source_id, team_id, integration_id in pending
            if team_by_integration.get(integration_id) == team_id
        ]
        ExternalDataSource.objects.bulk_update(updates, ["integration"], batch_size=BATCH_SIZE)
        pending.clear()

    # job_inputs is encrypted, so the reference can't be filtered in SQL — decrypt and scan in Python.
    sources = (
        ExternalDataSource.objects.exclude(deleted=True)
        .values_list("id", "team_id", "job_inputs")
        .iterator(chunk_size=BATCH_SIZE)
    )
    for source_id, team_id, job_inputs in sources:
        integration_id = _integration_id_from_job_inputs(job_inputs)
        if integration_id is not None:
            pending.append((source_id, team_id, integration_id))
        if len(pending) >= BATCH_SIZE:
            flush()
    flush()


def reverse(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    ExternalDataSource.objects.exclude(integration_id=None).update(integration_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0063_externaldatasource_integration"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
