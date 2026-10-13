import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlesearchconsole import (
    GoogleSearchConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.settings import (
    SEARCH_ANALYTICS_SCHEMAS,
    SEARCH_TYPES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source import (
    GoogleSearchConsoleSource,
)


def _config(search_types: list[str] | None = None) -> GoogleSearchConsoleSourceConfig:
    return GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
        search_types=search_types,
    )


def _all_types_config() -> GoogleSearchConsoleSourceConfig:
    return _config(list(SEARCH_TYPES))


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
        # The three `GoogleSearchConsoleQuotaExceededError` messages raised by `_query_search_analytics`
        # once its in-line quota retries run out. Each carries the `(retryable)` marker so the resumable
        # source resumes on the next Temporal retry instead of tracking the quota exhaustion as a bug.
        "Search Analytics daily quota for 'sc-domain:example.com' exhausted; retrying at the activity level (retryable)",
        "Search Analytics quota for 'sc-domain:example.com' still exhausted after 3 retries (retryable)",
        "Search Analytics quota for 'sc-domain:example.com' exhausted (retryable)",
    ],
)
def test_exhausted_quota_is_retryable(error_message):
    retryable_errors = GoogleSearchConsoleSource().get_retryable_errors()
    assert error_message_matches(error_message, retryable_errors)


@pytest.mark.parametrize(
    "status_code,body,expected_substring",
    [
        (401, {}, "Reconnect your Google account"),
        (403, {}, "can't read any Search Console property"),
        # A quota 403 says nothing about the connection, so it must not send the user reconnecting.
        (403, {"error": {"errors": [{"domain": "usageLimits", "reason": "rateLimitExceeded"}]}}, "rate limiting"),
    ],
)
def test_validate_credentials_handles_auth_failures(status_code, body, expected_substring):
    import requests

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
    ) as mock_session_factory:
        response = mock.MagicMock()
        response.status_code = status_code
        response.json.return_value = body
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


@pytest.mark.parametrize(
    "body,expected_substring",
    [
        ({}, "can't read any Search Console property"),
        ({"error": {"errors": [{"domain": "usageLimits", "reason": "rateLimitExceeded"}]}}, "rate limiting"),
    ],
)
def test_get_oauth_accounts_reports_why_the_property_list_failed(body, expected_substring):
    import requests

    from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
        IntegrationAccountListingError,
    )

    response = mock.MagicMock()
    response.status_code = 403
    response.json.return_value = body
    err = requests.HTTPError(response=response)

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            side_effect=err,
        ),
        pytest.raises(IntegrationAccountListingError) as raised,
    ):
        GoogleSearchConsoleSource().get_oauth_accounts(integration_id=1, team_id=1)

    assert expected_substring in str(raised.value)


def test_get_oauth_accounts_names_a_next_step_when_the_account_owns_no_property():
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
        IntegrationAccountListingError,
    )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[],
        ),
        pytest.raises(IntegrationAccountListingError) as raised,
    ):
        GoogleSearchConsoleSource().get_oauth_accounts(integration_id=1, team_id=1)

    assert "can't read any Search Console property" in str(raised.value)


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


def test_validate_credentials_says_to_reconnect_when_account_owns_no_property():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "can't read any Search Console property" in (message or "")
    assert "is not visible to the connected Google account" not in (message or "")


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


@pytest.mark.parametrize(
    "site_url",
    [
        "https://search.google.com/search-console/",
        "https://search.google.com/search-console/performance/search-analytics",
        "HTTPS://Search.Google.com/search-console",
    ],
)
def test_validate_credentials_rejects_the_search_console_dashboard_url(site_url):
    config = GoogleSearchConsoleSourceConfig(site_url=site_url, google_search_console_integration_id=1)
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.source.list_sites"
    ) as list_sites:
        ok, message = GoogleSearchConsoleSource().validate_credentials(config, team_id=1)

    assert ok is False
    assert "Search Console dashboard" in (message or "")
    assert "is not visible to the connected Google account" not in (message or "")
    list_sites.assert_not_called()
