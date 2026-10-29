import pytest

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    CREDENTIAL_KIND_EXCLUDED,
    CREDENTIAL_KIND_MAX_LENGTH,
    CREDENTIAL_KINDS_PATH,
    compute_credential_kinds,
    derive_credential_kind,
    kebab_case,
    oauth_kind_of,
    render_credential_kinds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_SOURCES = SourceRegistry.get_all_sources()
SOURCE_TYPES = sorted(ALL_SOURCES.keys(), key=str)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("AwsCloudTrail", "aws-cloud-trail"),
        ("Stripe", "stripe"),
        ("CustomerIO", "customer-io"),
        ("Dynamics365Sales", "dynamics365-sales"),
        ("GoogleSearchConsole", "google-search-console"),
        ("HTTPServer", "http-server"),
    ],
)
def test_kebab_case(name: str, expected: str) -> None:
    assert kebab_case(name) == expected


@pytest.mark.parametrize(
    "source_type,oauth_kind,expected",
    [
        (ExternalDataSourceType.POSTGRES, None, "postgresql"),
        (ExternalDataSourceType.REDSHIFT, None, "aws-redshift"),
        (ExternalDataSourceType.AMAZONS3, None, "aws-s3"),
        (ExternalDataSourceType.BIGQUERY, None, "google-cloud-service-account"),
        (ExternalDataSourceType.GITLAB, None, "gitlab"),
        (ExternalDataSourceType.APPLESEARCHADS, None, "apple-ads"),
        (ExternalDataSourceType.CUSTOMERIO, None, "customer-io"),
        (ExternalDataSourceType.MYSQL, None, "mysql"),
        (ExternalDataSourceType.MONGODB, None, "mongodb"),
        (ExternalDataSourceType.CLICKHOUSE, None, "clickhouse"),
        (ExternalDataSourceType.SHAREPOINT, None, "sharepoint"),
        (ExternalDataSourceType.TIKTOKADS, None, "tiktok-ads"),
        (ExternalDataSourceType.GITHUB, None, "github"),
        (ExternalDataSourceType.STRIPE, None, "stripe"),
        (ExternalDataSourceType.GOOGLECLOUDSTORAGE, None, "google-cloud-storage"),
        (ExternalDataSourceType.AWSCLOUDTRAIL, None, "aws-cloud-trail"),
        # The kind of the OAuth field wins, because those rows exist already.
        (ExternalDataSourceType.SNAPCHATADS, "snapchat", "snapchat"),
        (ExternalDataSourceType.POSTGRES, "custom-kind", "custom-kind"),
    ],
)
def test_derive_credential_kind(source_type: ExternalDataSourceType, oauth_kind: str | None, expected: str) -> None:
    assert derive_credential_kind(source_type, oauth_kind) == expected


@pytest.mark.parametrize(
    "source_type,expected",
    [
        (ExternalDataSourceType.SNAPCHATADS, "snapchat"),
        (ExternalDataSourceType.GOOGLEADS, "google-ads"),
        (ExternalDataSourceType.STRIPE, "stripe"),
        (ExternalDataSourceType.BIGQUERY, "google-cloud-service-account"),
        (ExternalDataSourceType.POSTGRES, None),
        (ExternalDataSourceType.CUSTOM, None),
    ],
)
def test_oauth_kind_of(source_type: ExternalDataSourceType, expected: str | None) -> None:
    assert oauth_kind_of(source_type) == expected


def test_custom_source_has_no_credential_kind() -> None:
    assert ExternalDataSourceType.CUSTOM in CREDENTIAL_KIND_EXCLUDED
    assert ExternalDataSourceType.CUSTOM.value not in CREDENTIAL_KINDS


@pytest.mark.parametrize("source_type", [s for s in SOURCE_TYPES if s not in CREDENTIAL_KIND_EXCLUDED], ids=str)
def test_every_source_has_a_valid_credential_kind(source_type: ExternalDataSourceType) -> None:
    kind = CREDENTIAL_KINDS[source_type.value]

    assert 0 < len(kind) <= CREDENTIAL_KIND_MAX_LENGTH
    assert kind == kind.lower()
    assert all(char.isalnum() or char == "-" for char in kind)
    assert not kind.startswith("-") and not kind.endswith("-")


def test_credential_kinds_are_unique_apart_from_shared_oauth_providers() -> None:
    sources_by_kind: dict[str, list[str]] = {}
    for source_type, kind in CREDENTIAL_KINDS.items():
        sources_by_kind.setdefault(kind, []).append(source_type)

    shared = {kind: types for kind, types in sources_by_kind.items() if len(types) > 1}
    assert not shared, f"Source types that share one credential kind: {shared}"


def test_credential_kinds_file_is_up_to_date() -> None:
    assert dict(CREDENTIAL_KINDS) == compute_credential_kinds()
    assert CREDENTIAL_KINDS_PATH.read_text() == render_credential_kinds(), (
        "The frozen credential kinds are out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )
