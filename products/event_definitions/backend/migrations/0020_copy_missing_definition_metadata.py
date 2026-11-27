"""Copy the ee definition rows that have no metadata row yet.

A save of an ee row copies it to the metadata tables, but rows saved before 0019_definition_metadata
reach those tables only through the `backfill_definition_metadata` command. A database where nobody
ran that command, such as a self-hosted one, would show those definitions without their metadata.
This migration copies only the missing rows, so it writes nothing where the command already ran.
"""

from django.db import migrations

from posthog.dataclasses import frozen

BATCH_SIZE = 1000
# Below every definition id, so the first page starts at the beginning of the primary key.
FIRST_ID = "00000000-0000-0000-0000-000000000000"


@frozen
class _MetadataCopy:
    enterprise_table: str
    enterprise_link: str
    definition_table: str
    metadata_table: str
    metadata_link: str
    columns: tuple[str, ...]


# The SQL stays in this file because the app code that copies these rows goes away with the ee tables.
COPIES = (
    _MetadataCopy(
        enterprise_table="ee_enterpriseeventdefinition",
        enterprise_link="eventdefinition_ptr_id",
        definition_table="posthog_eventdefinition",
        metadata_table="event_definitions_eventdefinitionmetadata",
        metadata_link="event_definition_id",
        columns=(
            "description",
            "updated_at",
            "updated_by_id",
            "verified",
            "verified_at",
            "verified_by_id",
            "hidden",
            "owner_id",
            "default_columns",
        ),
    ),
    _MetadataCopy(
        enterprise_table="ee_enterprisepropertydefinition",
        enterprise_link="propertydefinition_ptr_id",
        definition_table="posthog_propertydefinition",
        metadata_table="event_definitions_propertydefinitionmetadata",
        metadata_link="property_definition_id",
        columns=(
            "description",
            "updated_at",
            "updated_by_id",
            "verified",
            "verified_at",
            "verified_by_id",
            "hidden",
        ),
    ),
)


def copy_missing_definition_metadata(apps, schema_editor) -> None:
    connection = schema_editor.connection
    existing_tables = set(connection.introspection.table_names())
    for copy in COPIES:
        # A build without the ee app has no ee tables, so it has nothing to copy.
        if copy.enterprise_table not in existing_tables:
            continue
        _copy_missing_rows(connection, copy)


def _copy_missing_rows(connection, copy: _MetadataCopy) -> None:
    # Every identifier below is a constant of this file, and every value is a query parameter.
    find_missing_sql = f"""
        SELECT ee.{copy.enterprise_link} FROM {copy.enterprise_table} ee
        WHERE ee.{copy.enterprise_link} > %s::uuid
          AND NOT EXISTS (
            SELECT 1 FROM {copy.metadata_table} m WHERE m.{copy.metadata_link} = ee.{copy.enterprise_link}
          )
        ORDER BY ee.{copy.enterprise_link}
        LIMIT %s
    """
    # DO NOTHING keeps a row that a save copied while this migration ran, because that copy is newer.
    insert_sql = f"""
        INSERT INTO {copy.metadata_table} ({copy.metadata_link}, team_id, {", ".join(copy.columns)})
        SELECT ee.{copy.enterprise_link}, definition.team_id, {", ".join(f"ee.{column}" for column in copy.columns)}
        FROM {copy.enterprise_table} ee
        JOIN {copy.definition_table} definition ON definition.id = ee.{copy.enterprise_link}
        WHERE ee.{copy.enterprise_link} = ANY(%s::uuid[])
        ON CONFLICT ({copy.metadata_link}) DO NOTHING
    """
    after = FIRST_ID
    with connection.cursor() as cursor:
        while True:
            cursor.execute(find_missing_sql, [after, BATCH_SIZE])
            missing_ids = [row[0] for row in cursor.fetchall()]
            if not missing_ids:
                return
            cursor.execute(insert_sql, [missing_ids])
            after = missing_ids[-1]


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0019_definition_metadata"),
    ]

    operations = [
        migrations.RunPython(copy_missing_definition_metadata, migrations.RunPython.noop, elidable=True),
    ]
