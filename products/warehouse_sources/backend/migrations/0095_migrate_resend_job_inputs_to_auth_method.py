from django.db import migrations


def migrate_resend_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Resend"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        # Already migrated
        if "auth_method" in job_inputs:
            continue

        if "api_key" in job_inputs:
            api_key = job_inputs.pop("api_key")
            job_inputs["auth_method"] = {
                "selection": "api_key",
                "api_key": api_key,
            }

        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


def reverse_migrate_resend_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Resend"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        auth_method = job_inputs.get("auth_method")
        if not isinstance(auth_method, dict):
            continue

        if auth_method.get("selection") == "api_key":
            job_inputs["api_key"] = auth_method.get("api_key", "")

        job_inputs.pop("auth_method", None)
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0094_externaldatajob_updated_at_idx"),
    ]

    operations = [
        migrations.RunPython(migrate_resend_job_inputs, reverse_migrate_resend_job_inputs),
    ]
