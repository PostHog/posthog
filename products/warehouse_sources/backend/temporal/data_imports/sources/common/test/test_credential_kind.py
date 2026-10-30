import pytest
from unittest.mock import PropertyMock, patch

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    CREDENTIAL_KIND_MAX_LENGTH,
    CREDENTIAL_KINDS_PATH,
    ChangedFrozenValueError,
    compute_credential_kinds,
    default_credential_kind,
    frozen_credential_kinds,
    kebab_case,
    merge_append_only,
    oauth_kind_of,
    render_credential_kinds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_SOURCES = SourceRegistry.get_all_sources()
SOURCE_TYPES = sorted(ALL_SOURCES.keys(), key=str)
SOURCE_TYPES_WITH_KIND = [s for s in SOURCE_TYPES if ALL_SOURCES[s].credential_kind is not None]


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
    "source_type,expected",
    [
        # Sources that set their kind in their own class.
        (ExternalDataSourceType.POSTGRES, "postgresql"),
        (ExternalDataSourceType.REDSHIFT, "aws-redshift"),
        (ExternalDataSourceType.AMAZONS3, "aws-s3"),
        (ExternalDataSourceType.CUSTOMERIO, "customer-io"),
        (ExternalDataSourceType.MYSQL, "mysql"),
        (ExternalDataSourceType.TIKTOKADS, "tiktok-ads"),
        # Subclasses of an overriding source set their own kind.
        (ExternalDataSourceType.NEON, "neon"),
        (ExternalDataSourceType.SUPABASE, "supabase"),
        (ExternalDataSourceType.PLANETSCALEMYSQL, "planetscale-mysql"),
        (ExternalDataSourceType.AWSDOCUMENTDB, "aws-documentdb"),
        (ExternalDataSourceType.CUSTOM, None),
        # Sources that use the default.
        (ExternalDataSourceType.GITHUB, "github"),
        (ExternalDataSourceType.STRIPE, "stripe"),
        (ExternalDataSourceType.GOOGLECLOUDSTORAGE, "google-cloud-storage"),
        (ExternalDataSourceType.AWSCLOUDTRAIL, "aws-cloud-trail"),
        (ExternalDataSourceType.SNAPCHATADS, "snapchat"),
        (ExternalDataSourceType.GOOGLEADS, "google-ads"),
    ],
)
def test_credential_kind(source_type: ExternalDataSourceType, expected: str | None) -> None:
    assert ALL_SOURCES[source_type].credential_kind == expected


@pytest.mark.parametrize(
    "source_type,expected",
    [
        # The kind of the OAuth field wins, because those rows exist already.
        (ExternalDataSourceType.SNAPCHATADS, "snapchat"),
        (ExternalDataSourceType.BIGQUERY, "google-cloud-service-account"),
        (ExternalDataSourceType.YOUTUBEANALYTICS, "youtube-analytics"),
        # Without an OAuth field, the kebab-case source type. These sources override it.
        (ExternalDataSourceType.POSTGRES, "postgres"),
        (ExternalDataSourceType.MYSQL, "my-sql"),
        (ExternalDataSourceType.STRIPE, "stripe"),
    ],
)
def test_default_credential_kind(source_type: ExternalDataSourceType, expected: str) -> None:
    assert default_credential_kind(source_type, ALL_SOURCES[source_type].get_source_config) == expected


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
    assert oauth_kind_of(ALL_SOURCES[source_type].get_source_config) == expected


def test_compute_reads_the_kind_from_the_source_class() -> None:
    stripe = type(ALL_SOURCES[ExternalDataSourceType.STRIPE])
    with patch.object(stripe, "credential_kind", new_callable=PropertyMock, return_value="stripe-test"):
        kinds = compute_credential_kinds()

    assert kinds[ExternalDataSourceType.STRIPE.value] == "stripe-test"
    assert ExternalDataSourceType.CUSTOM.value not in kinds


def test_custom_source_has_no_credential_kind() -> None:
    assert ExternalDataSourceType.CUSTOM.value not in CREDENTIAL_KINDS


@pytest.mark.parametrize("source_type", SOURCE_TYPES_WITH_KIND, ids=str)
def test_every_source_has_a_valid_credential_kind(source_type: ExternalDataSourceType) -> None:
    kind = CREDENTIAL_KINDS[source_type.value]

    assert 0 < len(kind) <= CREDENTIAL_KIND_MAX_LENGTH
    assert kind == kind.lower()
    assert all(char.isalnum() or char == "-" for char in kind)
    assert not kind.startswith("-") and not kind.endswith("-")


def test_credential_kinds_are_unique() -> None:
    sources_by_kind: dict[str, list[str]] = {}
    for source_type, kind in CREDENTIAL_KINDS.items():
        sources_by_kind.setdefault(kind, []).append(source_type)

    shared = {kind: types for kind, types in sources_by_kind.items() if len(types) > 1}
    assert not shared, f"Source types that share one credential kind: {shared}"


@pytest.mark.parametrize(
    "_name,computed,allow_changed,expected",
    [
        ("unchanged", {"a": "x"}, False, {"a": "x"}),
        ("new_key_is_added", {"a": "x", "b": "y"}, False, {"a": "x", "b": "y"}),
        ("removed_key_stays", {}, False, {"a": "x"}),
        ("changed_value_raises", {"a": "z"}, False, ChangedFrozenValueError),
        ("changed_value_with_the_flag", {"a": "z"}, True, {"a": "z"}),
    ],
)
def test_merge_append_only(
    _name: str, computed: dict[str, str], allow_changed: bool, expected: dict[str, str] | type[Exception]
) -> None:
    if isinstance(expected, dict):
        assert merge_append_only({"a": "x"}, computed, name="kinds", allow_changed=allow_changed) == expected
    else:
        with pytest.raises(expected, match="--allow-changed-defaults"):
            merge_append_only({"a": "x"}, computed, name="kinds", allow_changed=allow_changed)


def test_a_changed_kind_fails_the_generation() -> None:
    stripe = type(ALL_SOURCES[ExternalDataSourceType.STRIPE])
    with patch.object(stripe, "credential_kind", new_callable=PropertyMock, return_value="stripe-test"):
        with pytest.raises(ChangedFrozenValueError, match="Stripe: 'stripe' -> 'stripe-test'"):
            render_credential_kinds()
        allowed = render_credential_kinds(allow_changed=True)

    assert '    "Stripe": "stripe-test",' in allowed


def test_credential_kinds_file_is_up_to_date() -> None:
    assert dict(CREDENTIAL_KINDS) == frozen_credential_kinds()
    assert CREDENTIAL_KINDS_PATH.read_text() == render_credential_kinds(), (
        "The frozen credential kinds are out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )
