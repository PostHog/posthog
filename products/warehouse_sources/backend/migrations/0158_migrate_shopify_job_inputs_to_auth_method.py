from django.db import migrations


def migrate_shopify_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Shopify"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        # Already migrated
        if "auth_method" in job_inputs:
            continue

        access_token = job_inputs.pop("shopify_access_token", None)
        client_id = job_inputs.pop("shopify_client_id", None)
        client_secret = job_inputs.pop("shopify_client_secret", None)

        if access_token:
            job_inputs["auth_method"] = {
                "selection": "access_token",
                "shopify_access_token": access_token,
            }
        else:
            job_inputs["auth_method"] = {
                "selection": "client_credentials",
                "shopify_client_id": client_id,
                "shopify_client_secret": client_secret,
            }

        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


def reverse_migrate_shopify_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Shopify"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        auth_method = job_inputs.get("auth_method")
        if not isinstance(auth_method, dict):
            continue

        if auth_method.get("selection") == "access_token":
            job_inputs["shopify_access_token"] = auth_method.get("shopify_access_token", "")
        else:
            job_inputs["shopify_client_id"] = auth_method.get("shopify_client_id", "")
            job_inputs["shopify_client_secret"] = auth_method.get("shopify_client_secret", "")

        job_inputs.pop("auth_method", None)
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0157_reset_plausible_page_breakdowns"),
    ]

    operations = [
        migrations.RunPython(migrate_shopify_job_inputs, reverse_migrate_shopify_job_inputs),
    ]
