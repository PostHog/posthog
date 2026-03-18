from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def fix_variable_keys(apps, schema_editor):
    """Fix endpoints where query.variables keys are 'var_0', 'var_1' instead of variableId.

    The frontend was incorrectly saving variables with keys like 'var_0' instead of
    using the actual variableId. This migration re-keys the variables dict to use
    the variableId from each variable's value.
    """
    Endpoint = apps.get_model("endpoints", "Endpoint")
    EndpointVersion = apps.get_model("endpoints", "EndpointVersion")

    def rekey_variables(variables: dict) -> tuple[dict, bool]:
        """Transform variables dict to use variableId as key.

        Returns: (new_variables_dict, was_modified)
        """
        if not variables:
            return variables, False

        needs_fix = any(key.startswith("var_") for key in variables.keys())
        if not needs_fix:
            return variables, False

        new_variables = {}
        for key, value in variables.items():
            variable_id = value.get("variableId")
            if variable_id:
                new_variables[variable_id] = value
            else:
                new_variables[key] = value

        return new_variables, True

    endpoints_updated = 0
    for endpoint in Endpoint.objects.all():
        query = endpoint.query
        if not query or query.get("kind") != "HogQLQuery":
            continue

        variables = query.get("variables", {})
        new_variables, was_modified = rekey_variables(variables)

        if was_modified:
            query["variables"] = new_variables
            endpoint.query = query
            endpoint.save(update_fields=["query"])
            endpoints_updated += 1

    versions_updated = 0
    for version in EndpointVersion.objects.all():
        query = version.query
        if not query or query.get("kind") != "HogQLQuery":
            continue

        variables = query.get("variables", {})
        new_variables, was_modified = rekey_variables(variables)

        if was_modified:
            query["variables"] = new_variables
            version.query = query
            version.save(update_fields=["query"])
            versions_updated += 1

    logger.info(
        "finished_0007_fix_hogql_variable_keys",
        endpoints_updated=endpoints_updated,
        versions_updated=versions_updated,
    )


def reverse_migration(apps, schema_editor):
    """No-op reverse migration.

    We can't reverse this migration because we don't know what the original
    var_X keys were and they're broken anyways.
    The new format is correct and backwards compatible.
    """
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0006_endpoint_derived_from_insight"),
    ]

    operations = [
        migrations.RunPython(fix_variable_keys, reverse_migration),
    ]
