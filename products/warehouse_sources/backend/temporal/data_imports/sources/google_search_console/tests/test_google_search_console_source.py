import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleSearchConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console import (
    GoogleSearchConsoleResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.settings import (
    SEARCH_ANALYTICS_SCHEMAS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source import (
    GoogleSearchConsoleSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _config() -> GoogleSearchConsoleSourceConfig:
    return GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )


def test_source_type():
    assert GoogleSearchConsoleSource().source_type == ExternalDataSourceType.GOOGLESEARCHCONSOLE


def test_get_source_config_fields():
    cfg = GoogleSearchConsoleSource().get_source_config

    field_names = {field.name for field in cfg.fields}
    assert field_names == {"google_search_console_integration_id", "site_url"}
    assert cfg.label == "Google Search Console"
    assert cfg.featureFlag is None
    assert cfg.releaseStatus == "ga"


def test_get_schemas_returns_all_schemas_with_date_incremental():
    schemas = GoogleSearchConsoleSource().get_schemas(_config(), team_id=1)

    assert {s.name for s in schemas} == set(SEARCH_ANALYTICS_SCHEMAS.keys())
    for schema in schemas:
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


def test_get_schemas_only_query_page_default():
    schemas = GoogleSearchConsoleSource().get_schemas(_config(), team_id=1)
    by_default_on = {s.name for s in schemas if s.should_sync_default}
    assert by_default_on == {"search_analytics_by_query_page"}


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


def test_get_resumable_source_manager_uses_resume_config():
    inputs = mock.MagicMock()
    manager = GoogleSearchConsoleSource().get_resumable_source_manager(inputs)
    assert manager._data_class is GoogleSearchConsoleResumeConfig


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
