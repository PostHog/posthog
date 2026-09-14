from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

# TEXT connection strings only prefill the credential fields the connection uses, so the edit form
# hides them. PASSWORD ones are the credential itself, so the edit form keeps them editable.
_EXPECTED_TYPE_BY_SOURCE = {
    "ClickHouse": SourceFieldInputConfigType.TEXT,
    "MSSQL": SourceFieldInputConfigType.TEXT,
    "MongoDB": SourceFieldInputConfigType.PASSWORD,
    "Neon": SourceFieldInputConfigType.TEXT,
    "PlanetScalePostgres": SourceFieldInputConfigType.TEXT,
    "Postgres": SourceFieldInputConfigType.TEXT,
    "Redshift": SourceFieldInputConfigType.TEXT,
    "Snowflake": SourceFieldInputConfigType.TEXT,
    "Supabase": SourceFieldInputConfigType.TEXT,
}


def test_connection_string_field_type_matches_credential_role():
    for source_type, source in SourceRegistry.get_all_sources().items():
        connection_string = next(
            (
                f
                for f in source.get_source_config.fields
                if isinstance(f, SourceFieldInputConfig) and f.name == "connection_string"
            ),
            None,
        )
        if connection_string is None:
            continue

        expected_type = _EXPECTED_TYPE_BY_SOURCE.get(str(source_type))
        assert expected_type is not None, (
            f"{source_type} declares a connection_string but is missing from _EXPECTED_TYPE_BY_SOURCE. "
            f"Add it as PASSWORD if the connection string is the whole credential (so it stays editable "
            f"for rotation), or TEXT if it only prefills other credential fields."
        )
        assert connection_string.type == expected_type, (
            f"{source_type} declares connection_string as {connection_string.type}, expected {expected_type}. "
            f"PASSWORD stays editable on update for rotation, TEXT is hidden there."
        )
