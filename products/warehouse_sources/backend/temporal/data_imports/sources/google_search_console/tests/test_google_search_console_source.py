import pytest
from unittest import mock

import requests

from posthog.schema import SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlesearchconsole import (
    GoogleSearchConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.settings import (
    DEFAULT_SEARCH_TYPE,
    PROPERTY_SCHEMAS,
    SEARCH_ANALYTICS_SCHEMAS,
    SEARCH_TYPES,
    qualified_schema_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source import (
    GoogleSearchConsoleSource,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def _config(search_types: list[str] | None = None) -> GoogleSearchConsoleSourceConfig:
    return GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
        search_types=search_types,
    )


def _all_types_config() -> GoogleSearchConsoleSourceConfig:
    return _config(list(SEARCH_TYPES))


def _expected_names(search_types: list[str]) -> set[str]:
    return {
        qualified_schema_name(base_name, search_type)
        for search_type in search_types
        for base_name, schema in SEARCH_ANALYTICS_SCHEMAS.items()
        if search_type == DEFAULT_SEARCH_TYPE or not schema.get("web_only")
    } | set(PROPERTY_SCHEMAS.keys())


def test_get_source_config_fields():
    cfg = GoogleSearchConsoleSource().get_source_config

    field_names = {field.name for field in cfg.fields}
    assert field_names == {"google_search_console_integration_id", "site_url", "search_types"}
    assert cfg.label == "Google Search Console"
    assert cfg.featureFlag is None
    assert cfg.releaseStatus == "ga"

    search_types = next(field for field in cfg.fields if field.name == "search_types")
    assert isinstance(search_types, SourceFieldSelectConfig)
    # Without `multiple` the form stores a bare string and only one type can ever sync.
    assert search_types.multiple is True
    assert search_types.defaultValue == DEFAULT_SEARCH_TYPE
    assert tuple(option.value for option in search_types.options) == SEARCH_TYPES


def test_get_schemas_returns_all_schemas_with_date_incremental():
    schemas = GoogleSearchConsoleSource().get_schemas(_all_types_config(), team_id=1)

    assert {s.name for s in schemas} == _expected_names(list(SEARCH_TYPES))
    for schema in schemas:
        if schema.name in PROPERTY_SCHEMAS:
            continue
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert schema.incremental_fields == [
            {
                "label": "date",
                "field": "date",
                "type": IncrementalFieldType.Date,
                "field_type": IncrementalFieldType.Date,
            }
        ]


@pytest.mark.parametrize("name", sorted(PROPERTY_SCHEMAS.keys()))
def test_property_schemas_are_not_incremental(name):
    # `sites.list` and `sitemaps.list` return the current state with no timestamp to filter on,
    # so offering incremental sync would checkpoint a watermark that can never advance.
    schema = next(s for s in GoogleSearchConsoleSource().get_schemas(_config(), team_id=1) if s.name == name)

    assert schema.supports_incremental is False
    assert schema.supports_append is False
    assert schema.incremental_fields == []


@pytest.mark.parametrize(
    "config",
    [
        pytest.param(_config(), id="unset_defaults_to_web"),
        pytest.param(_config([]), id="empty_defaults_to_web"),
        pytest.param(_all_types_config(), id="all_types"),
        pytest.param(_config(["news", "web"]), id="subset"),
    ],
)
def test_get_schemas_default_on_tables(config):
    schemas = GoogleSearchConsoleSource().get_schemas(config, team_id=1)
    by_default_on = {s.name for s in schemas if s.should_sync_default}
    # Search analytics tables are opt-in apart from the most useful one; the property metadata
    # tables are one cheap request each per sync, so they stay on. Picking an extra search type
    # must never switch one on, since each table costs a full history backfill.
    assert by_default_on == {"search_analytics_by_query_page", *PROPERTY_SCHEMAS.keys()}


@pytest.mark.parametrize(
    "search_types,expected_types",
    [
        # A config saved before search types existed must keep exactly its current tables.
        (None, [DEFAULT_SEARCH_TYPE]),
        ([], [DEFAULT_SEARCH_TYPE]),
        (["image", "web"], ["web", "image"]),
        (["news", "news"], ["news"]),
        (["discover", "image"], ["image"]),
        (list(SEARCH_TYPES), list(SEARCH_TYPES)),
    ],
)
def test_effective_search_types(search_types, expected_types):
    assert GoogleSearchConsoleSource.effective_search_types(_config(search_types)) == expected_types


@pytest.mark.parametrize(
    "search_types",
    [None, ["web"], ["image"], ["web", "image", "news"], list(SEARCH_TYPES)],
)
def test_get_schemas_cross_product_excludes_web_only_tables(search_types):
    schemas = GoogleSearchConsoleSource().get_schemas(_config(search_types), team_id=1)
    effective = GoogleSearchConsoleSource.effective_search_types(_config(search_types))

    assert {s.name for s in schemas} == _expected_names(effective)
    # Hourly and search appearance data only exist for web search.
    for web_only_name in ("search_analytics_by_hour", "search_analytics_by_search_appearance"):
        for search_type in effective:
            if search_type == DEFAULT_SEARCH_TYPE:
                continue
            assert qualified_schema_name(web_only_name, search_type) not in {s.name for s in schemas}


def test_search_appearance_schema_uses_solo_dimension_with_date_in_pk():
    # Google's API refuses to group `searchAppearance` with any other dimension,
    # so the schema must request it alone — but the warehouse still partitions per
    # day, which is why `date` lives in the primary key (injected by the iterator).
    schema = SEARCH_ANALYTICS_SCHEMAS["search_analytics_by_search_appearance"]
    assert schema["dimensions"] == ["searchAppearance"]
    assert schema["primary_key"] == ["date", "searchAppearance"]
    assert schema["should_sync_default"] is False


def test_get_schemas_filters_by_names():
    schemas = GoogleSearchConsoleSource().get_schemas(
        _config(), team_id=1, names=["search_analytics_by_date", "search_analytics_by_query"]
    )
    assert {s.name for s in schemas} == {"search_analytics_by_date", "search_analytics_by_query"}


@pytest.mark.parametrize(
    "config",
    [pytest.param(_config(), id="web_only"), pytest.param(_all_types_config(), id="all_types")],
)
def test_canonical_descriptions_cover_every_schema(config):
    # A table shipped without a canonical entry silently falls back to LLM-generated
    # descriptions, which is what the curated file exists to avoid.
    source = GoogleSearchConsoleSource()
    names = {s.name for s in source.get_schemas(config, team_id=1)}

    assert names <= set(source.get_canonical_descriptions().keys())


@pytest.mark.parametrize(
    "error_message",
    [
        "invalid_grant",
        # The real RefreshError raised when AuthorizedSession refreshes a revoked/expired token.
        "RefreshError: ('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
    ],
)
def test_invalid_grant_is_non_retryable(error_message):
    non_retryable_errors = GoogleSearchConsoleSource().get_non_retryable_errors()
    assert any(key in error_message for key in non_retryable_errors)


def test_missing_integration_is_non_retryable():
    # The message raised mid-sync by Integration.objects.get when the row was deleted.
    error_message = "Integration matching query does not exist."
    non_retryable_errors = GoogleSearchConsoleSource().get_non_retryable_errors()
    assert any(key in error_message for key in non_retryable_errors)


@pytest.mark.parametrize(
    "status_code,expected_substring",
    [
        (401, "rejected the credentials"),
        (403, "rejected the credentials"),
    ],
)
def test_validate_credentials_handles_auth_failures(status_code, expected_substring):
    import requests

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
    ) as mock_session_factory:
        response = mock.MagicMock()
        response.status_code = status_code
        err = requests.HTTPError(response=response)
        session = mock.MagicMock()
        session.get.return_value.raise_for_status.side_effect = err
        mock_session_factory.return_value = session

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            side_effect=err,
        ):
            ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert expected_substring in (message or "")


def test_validate_credentials_missing_integration_returns_reconnect_message():
    from posthog.models.integration import Integration

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session",
        side_effect=Integration.DoesNotExist(),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "no longer exists" in (message or "")
    assert "Integration matching query" not in (message or "")


@pytest.mark.parametrize(
    "error_args,banned_substring",
    [
        (
            ("invalid_scope: Bad Request", {"error": "invalid_scope", "error_description": "Bad Request"}),
            "invalid_scope",
        ),
        (
            ("invalid_grant: Token has been expired or revoked.", {"error": "invalid_grant"}),
            "invalid_grant",
        ),
    ],
)
def test_validate_credentials_refresh_error_returns_reconnect_message(error_args, banned_substring):
    from google.auth.exceptions import RefreshError

    err = RefreshError(*error_args)
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            side_effect=err,
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "reconnect your Google account" in (message or "")
    assert banned_substring not in (message or "")


def test_validate_credentials_rejects_unknown_site():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[
                {"siteUrl": "https://other.example.com/", "permissionLevel": "siteOwner"},
            ],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "is not visible to the connected Google account" in (message or "")


def test_validate_credentials_suggests_registered_property_for_bare_hostname():
    # User entered a bare hostname; the account has the URL-prefix property. Point them
    # at the exact string to paste rather than the dead-end "not visible" message.
    config = GoogleSearchConsoleSourceConfig(site_url="plotlens.ai", google_search_console_integration_id=1)
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[{"siteUrl": "https://plotlens.ai/", "permissionLevel": "siteOwner"}],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(config, team_id=1)

    assert ok is False
    assert "https://plotlens.ai/" in (message or "")
    assert "is not visible to the connected Google account" not in (message or "")


def test_validate_credentials_rejects_unverified_user():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[
                {"siteUrl": "https://example.com/", "permissionLevel": "siteUnverifiedUser"},
            ],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "verified access" in (message or "")


@pytest.mark.parametrize(
    "entered,site_url",
    [
        # Percent-encoded domain property copied from a URL bar.
        ("sc-domain%3Aexample.com", "sc-domain:example.com"),
        # URL-prefix property missing its trailing slash.
        ("https://example.com", "https://example.com/"),
        # Full Search Console UI URL pasted in.
        (
            "https://search.google.com/search-console/performance/search-analytics"
            "?resource_id=https%3A%2F%2Fexample.com%2F",
            "https://example.com/",
        ),
    ],
)
def test_validate_credentials_normalizes_site_url_before_lookup(entered, site_url):
    config = GoogleSearchConsoleSourceConfig(site_url=entered, google_search_console_integration_id=1)
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[{"siteUrl": site_url, "permissionLevel": "siteOwner"}],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(config, team_id=1)

    assert ok is True
    assert message is None


def test_validate_credentials_succeeds_for_verified_site():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[
                {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
            ],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is True
    assert message is None


def test_validate_credentials_handles_missing_integration():
    # A disconnected/deleted OAuth integration makes the credentials lookup raise
    # `Integration.DoesNotExist` ("... matching query does not exist"). Surface an
    # actionable reconnect message instead of the raw ORM error.
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session",
        side_effect=Exception("Integration matching query does not exist"),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "reconnect your Google Search Console account" in (message or "")


def _http_error(status_code: int, message: str = "") -> requests.HTTPError:
    response = mock.MagicMock()
    response.status_code = status_code
    return requests.HTTPError(message, response=response)


def test_validate_credentials_unexpected_load_error_stays_generic():
    # An unexpected failure loading the connection (not the deleted-integration case) must not
    # surface the raw exception, which can embed OAuth tokens or ids.
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session",
        side_effect=Exception("boom access_token=secret-abc123"),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "reconnect your Google account" in (message or "")
    assert "secret-abc123" not in (message or "")


@pytest.mark.parametrize(
    "error,secret",
    [
        pytest.param(_http_error(500, "boom access_token=secret-http500"), "secret-http500", id="http_500"),
        pytest.param(Exception("boom refresh_token=secret-xyz789"), "secret-xyz789", id="unexpected"),
    ],
)
def test_validate_credentials_unexpected_list_sites_error_stays_generic(error, secret):
    # A non-auth failure listing sites must fall back to a generic message, not leak the raw error.
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            side_effect=error,
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "couldn't reach Google Search Console" in (message or "")
    assert secret not in (message or "")
