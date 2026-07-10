import pytest

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.versioning import (
    VersionDeprecation,
    resolve_api_version,
)

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


@pytest.mark.parametrize(
    "pinned,default,expected",
    [
        (None, "v1", "v1"),
        ("v1", "v1", "v1"),
        ("2024-09-30.acacia", "2026-02-25.clover", "2024-09-30.acacia"),
        ("", "v1", "v1"),
    ],
)
def test_resolve_api_version_honors_pin_and_falls_back_to_default(pinned, default, expected):
    assert resolve_api_version(pinned, default) == expected
