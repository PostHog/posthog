import pytest

from posthog.schema import SourceConfig

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation, _BaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_SOURCES = SourceRegistry.get_all_sources()
SOURCE_TYPES = sorted(ALL_SOURCES.keys(), key=str)


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_every_source_declares_valid_versions(source_type):
    source = ALL_SOURCES[source_type]

    assert isinstance(source.supported_versions, tuple), (
        f"{source_type}: supported_versions must be a tuple of version strings"
    )
    assert len(source.supported_versions) > 0, f"{source_type}: supported_versions must not be empty"
    assert all(isinstance(v, str) and v for v in source.supported_versions), (
        f"{source_type}: every supported version must be a non-empty string"
    )
    assert len(set(source.supported_versions)) == len(source.supported_versions), (
        f"{source_type}: supported_versions contains duplicates"
    )
    assert source.default_version in source.supported_versions, (
        f"{source_type}: default_version {source.default_version!r} is not in supported_versions — "
        f"a missing pin would resolve to a version the source does not implement"
    )

    assert all(isinstance(d, VersionDeprecation) for d in source.deprecated_versions), (
        f"{source_type}: deprecated_versions must contain VersionDeprecation entries"
    )
    deprecated = {d.version for d in source.deprecated_versions}
    assert deprecated <= set(source.supported_versions), (
        f"{source_type}: deprecated_versions {deprecated - set(source.supported_versions)} are not declared "
        f"in supported_versions"
    )
    assert source.default_version not in deprecated, (
        f"{source_type}: default_version must not be deprecated — new sources would be pinned to it"
    )

    if source.api_docs_url is not None:
        assert source.api_docs_url.startswith("https://"), (
            f"{source_type}: api_docs_url must be an https URL, got {source.api_docs_url!r}"
        )

    for schema_name, schema_versions in source.schema_supported_versions.items():
        assert isinstance(schema_versions, tuple) and len(schema_versions) > 0, (
            f"{source_type}: schema_supported_versions[{schema_name!r}] must be a non-empty tuple"
        )
        assert all(isinstance(v, str) and v for v in schema_versions), (
            f"{source_type}: schema_supported_versions[{schema_name!r}] must contain non-empty strings"
        )
        assert len(set(schema_versions)) == len(schema_versions), (
            f"{source_type}: schema_supported_versions[{schema_name!r}] contains duplicates"
        )
        assert set(schema_versions) <= set(source.supported_versions), (
            f"{source_type}: schema_supported_versions[{schema_name!r}] declares versions "
            f"{set(schema_versions) - set(source.supported_versions)} the source does not implement"
        )
        assert set(schema_versions) != set(source.supported_versions), (
            f"{source_type}: schema {schema_name!r} is available on every supported version — "
            f"remove the redundant entry"
        )

    # A typo'd schema name silently never matches — the schema keeps following the source pin
    # and fails at the vendor. Verifiable only for static-catalog sources (no I/O in get_schemas).
    if source.schema_supported_versions and source.lists_tables_without_credentials:
        catalog = {s.name for s in source.get_schemas(source._placeholder_config(), team_id=0)}
        unknown_schemas = set(source.schema_supported_versions) - catalog
        assert not unknown_schemas, (
            f"{source_type}: schema_supported_versions declares schemas {sorted(unknown_schemas)} "
            f"that get_schemas does not list"
        )


def test_resolve_api_version_honors_pin_and_falls_back_to_default():
    source = ALL_SOURCES[SOURCE_TYPES[0]]
    assert source.resolve_api_version(None) == source.default_version
    assert source.resolve_api_version("") == source.default_version
    assert source.resolve_api_version("some-undeclared-label") == "some-undeclared-label"


class _VersionedSchemasSource(_BaseSource):
    supported_versions = ("V1", "V2")
    default_version = "V2"
    schema_supported_versions = {"v1_only": ("V1",), "v2_only": ("V2",)}

    @property
    def source_type(self) -> ExternalDataSourceType:
        raise NotImplementedError()

    @property
    def get_source_config(self) -> SourceConfig:
        raise NotImplementedError()


@pytest.mark.parametrize(
    "schema_name,override,pin,expected",
    [
        ("unlisted", None, None, "V2"),  # undeclared schema, no pin: source default
        ("unlisted", None, "retired", "retired"),  # undeclared schema honors even a retired pin verbatim
        ("v1_only", "V9", "V2", "V9"),  # user override honored verbatim, even undeclared
        ("v1_only", None, "V1", "V1"),  # declared schema follows a pin it is available on
        ("v1_only", None, "V2", "V1"),  # dropped-in-V2 schema on a V2 source syncs on its fallback
        ("v2_only", None, "V1", "V2"),  # new-in-V2 schema on a V1 source syncs on its fallback
    ],
)
def test_resolve_schema_api_version_precedence(schema_name, override, pin, expected):
    assert _VersionedSchemasSource().resolve_schema_api_version(schema_name, override, pin) == expected
