from django.db import migrations


def populate_version_fields(apps, schema_editor):
    """
    Copy version-specific fields from Endpoint to EndpointVersion.

    - description and cache_age_seconds: copied to ALL versions (shared metadata)
    - saved_query, is_materialized: only to current version
      (materialization is tied to the specific query)
    """
    Endpoint = apps.get_model("endpoints", "Endpoint")
    EndpointVersion = apps.get_model("endpoints", "EndpointVersion")

    for endpoint in Endpoint.objects.select_related("saved_query").all():
        # Copy description and cache_age to ALL versions
        EndpointVersion.objects.filter(endpoint=endpoint).update(
            description=endpoint.description or "",
            cache_age_seconds=endpoint.cache_age_seconds,
        )

        # Copy materialization state only to current version
        if endpoint.saved_query:
            EndpointVersion.objects.filter(endpoint=endpoint, version=endpoint.current_version).update(
                saved_query=endpoint.saved_query,
                is_materialized=True,
            )


def reverse_migration(apps, schema_editor):
    """Clear the version-specific fields."""
    EndpointVersion = apps.get_model("endpoints", "EndpointVersion")
    EndpointVersion.objects.update(
        description="",
        cache_age_seconds=None,
        saved_query=None,
        is_materialized=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0009_endpointversion_version_fields"),
    ]

    operations = [
        migrations.RunPython(populate_version_fields, reverse_migration),
    ]
