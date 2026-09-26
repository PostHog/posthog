from django.db import migrations

LEGACY_FIELDS = ("subdomain", "api_key", "email_address")


def migrate_zendesk_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Zendesk").iterator():
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict) or "auth_method" in job_inputs:
            continue

        job_inputs["auth_method"] = {
            "selection": "api_key",
            **{field: job_inputs.pop(field, None) for field in LEGACY_FIELDS},
        }
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


def reverse_migrate_zendesk_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Zendesk").iterator():
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue
        auth_method = job_inputs.get("auth_method")
        # An OAuth source has no token to restore, so it stays on the new shape.
        if not isinstance(auth_method, dict) or auth_method.get("selection") != "api_key":
            continue

        for field in LEGACY_FIELDS:
            job_inputs[field] = auth_method.get(field) or ""
        job_inputs.pop("auth_method")
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0168_externaldataschema_scheduled_full_refresh"),
    ]

    operations = [
        migrations.RunPython(migrate_zendesk_job_inputs, reverse_migrate_zendesk_job_inputs),
    ]
