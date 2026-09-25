import pytest
from unittest import mock

from django.core.cache import cache

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleadsense import (
    GoogleAdSenseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.settings import (
    ENTITY_SCHEMAS,
    REPORTS_SCHEMAS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.source import GoogleAdSenseSource

_SRC = "products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.source"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _config(**overrides) -> GoogleAdSenseSourceConfig:
    defaults = {
        "google_adsense_integration_id": 1,
        "account": "accounts/pub-1234567890",
        "start_date": None,
    }
    defaults.update(overrides)
    return GoogleAdSenseSourceConfig(**defaults)


def _fake_response(status_code: int, json_body: dict | None = None):
    resp = mock.MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


def _error_info(reason: str) -> dict:
    return {
        "error": {
            "code": 403,
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}],
        }
    }


_QUOTA_BODY = _error_info("quotaExceeded")
_PERMISSION_BODY = _error_info("forbidden")


def test_get_source_config_fields():
    cfg = GoogleAdSenseSource().get_source_config
    field_names = {field.name for field in cfg.fields}
    assert field_names == {"google_adsense_integration_id", "account", "start_date"}
    assert cfg.label == "Google AdSense"


def test_oauth_field_declares_the_adsense_readonly_scope():
    cfg = GoogleAdSenseSource().get_source_config
    oauth = next(field for field in cfg.fields if field.name == "google_adsense_integration_id")
    assert oauth.kind == "google-adsense"
    assert oauth.requiredScopes == "https://www.googleapis.com/auth/adsense.readonly"


def test_get_schemas_returns_all_reports_and_entity_tables():
    schemas = GoogleAdSenseSource().get_schemas(_config(), team_id=1)
    assert {s.name for s in schemas} == set(REPORTS_SCHEMAS.keys()) | set(ENTITY_SCHEMAS.keys())


def test_get_schemas_reports_tables_are_incremental_on_date():
    schemas = GoogleAdSenseSource().get_schemas(_config(), team_id=1)
    for schema in schemas:
        if schema.name not in REPORTS_SCHEMAS:
            continue
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert len(schema.incremental_fields) == 1
        assert schema.incremental_fields[0]["field"] == "date"


@pytest.mark.parametrize("name", sorted(ENTITY_SCHEMAS.keys()))
def test_entity_schemas_are_not_incremental(name):
    # Every entity endpoint returns the current account/inventory state with no
    # timestamp to filter on, so offering incremental sync would checkpoint a
    # watermark that can never advance.
    schema = next(s for s in GoogleAdSenseSource().get_schemas(_config(), team_id=1) if s.name == name)
    assert schema.supports_incremental is False
    assert schema.supports_append is False


def test_get_schemas_default_on_tables():
    schemas = GoogleAdSenseSource().get_schemas(_config(), team_id=1)
    by_default_on = {s.name for s in schemas if s.should_sync_default}
    expected_default_reports = {name for name, schema in REPORTS_SCHEMAS.items() if schema["should_sync_default"]}
    expected_default_entities = {name for name, schema in ENTITY_SCHEMAS.items() if schema["should_sync_default"]}
    assert by_default_on == expected_default_reports | expected_default_entities
    # High-cardinality table is off by default.
    assert "page_url_stats" not in by_default_on


def test_get_schemas_filters_by_names():
    schemas = GoogleAdSenseSource().get_schemas(_config(), team_id=1, names=["daily_stats", "ad_unit_stats"])
    assert {s.name for s in schemas} == {"daily_stats", "ad_unit_stats"}


def test_canonical_descriptions_cover_every_schema():
    # A table shipped without a canonical entry silently falls back to LLM-generated
    # descriptions, which is what the curated file exists to avoid.
    source = GoogleAdSenseSource()
    names = {s.name for s in source.get_schemas(_config(), team_id=1)}
    assert names <= set(source.get_canonical_descriptions().keys())


def test_stats_canonical_descriptions_document_the_currency_column():
    descriptions = GoogleAdSenseSource().get_canonical_descriptions()
    assert "currency_code" in descriptions["daily_stats"]["columns"]


@pytest.mark.parametrize(
    "error_message",
    [
        "invalid_grant",
        "RefreshError: ('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
    ],
)
def test_invalid_grant_is_non_retryable(error_message):
    non_retryable_errors = GoogleAdSenseSource().get_non_retryable_errors()
    assert any(key in error_message for key in non_retryable_errors)


def test_missing_integration_is_non_retryable():
    error_message = "Integration matching query does not exist."
    non_retryable_errors = GoogleAdSenseSource().get_non_retryable_errors()
    assert any(key in error_message for key in non_retryable_errors)


@pytest.mark.parametrize(
    "error_message",
    [
        "AdSense daily quota for 'accounts/pub-1' exhausted; retrying at the activity level (retryable)",
        "AdSense reports quota for 'accounts/pub-1' still exhausted after 5 retries (retryable)",
        "AdSense reports quota for 'accounts/pub-1' exhausted (retryable)",
        "AdSense quota exhausted fetching https://adsense.googleapis.com/v2/accounts/pub-1/sites (retryable)",
    ],
)
def test_exhausted_quota_is_retryable(error_message):
    retryable_errors = GoogleAdSenseSource().get_retryable_errors()
    assert any(key in error_message for key in retryable_errors)


# ---------------------------------------------------------------------------
# validate_credentials
# ---------------------------------------------------------------------------


def test_validate_credentials_missing_integration_returns_reconnect_message():
    from posthog.models.integration import Integration

    with mock.patch(f"{_SRC}.google_adsense_session", side_effect=Integration.DoesNotExist()):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "no longer exists" in (message or "")


def test_validate_credentials_unexpected_load_error_stays_generic():
    # An unexpected failure loading the connection must not surface the raw exception,
    # which can embed OAuth tokens or ids.
    with mock.patch(f"{_SRC}.google_adsense_session", side_effect=Exception("boom access_token=secret-abc123")):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "reconnect your Google account" in (message or "")
    assert "secret-abc123" not in (message or "")


def test_validate_credentials_deleted_integration_message_via_generic_exception():
    with mock.patch(f"{_SRC}.google_adsense_session", side_effect=Exception("matching query does not exist")):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "no longer available" in (message or "") or "reconnect" in (message or "").lower()


def test_validate_credentials_refresh_error_returns_reconnect_message():
    from google.auth.exceptions import RefreshError

    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(
            f"{_SRC}.get_account", side_effect=RefreshError("invalid_grant: Token has expired or been revoked.")
        ),
    ):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "reconnect" in (message or "").lower()


def test_validate_credentials_rejects_a_non_ready_account():
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.get_account", return_value={"name": "accounts/pub-1", "state": "NEEDS_ATTENTION"}),
    ):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "can't read any AdSense account" in (message or "")


def test_validate_credentials_succeeds_for_ready_account():
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.get_account", return_value={"name": "accounts/pub-1", "state": "READY"}),
    ):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is True
    assert message is None


def test_validate_credentials_validates_the_selected_account_not_just_the_list():
    # accounts.get on the *selected* account is the probe — a list-only check would miss a
    # stale/inaccessible account value.
    with (
        mock.patch(f"{_SRC}.google_adsense_session") as session_mock,
        mock.patch(f"{_SRC}.get_account", return_value={"state": "READY"}) as get_account_mock,
        mock.patch(f"{_SRC}.list_accounts") as list_accounts_mock,
    ):
        ok, _ = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is True
    get_account_mock.assert_called_once_with(session_mock.return_value, "accounts/pub-1234567890")
    list_accounts_mock.assert_not_called()


@pytest.mark.parametrize(
    "status_code,body,expected_substring",
    [
        (401, {}, "Google rejected the credentials"),
        (403, _PERMISSION_BODY, "can't read any AdSense account"),
        # A quota 403 says nothing about the connection, so it must not send the user reconnecting.
        (403, _QUOTA_BODY, "rate limiting"),
    ],
)
def test_validate_credentials_handles_auth_failures(status_code, body, expected_substring):
    response = _fake_response(status_code, body)
    err = requests.HTTPError(response=response)
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.get_account", side_effect=err),
    ):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert expected_substring in (message or "")


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_validate_credentials_maps_transient_5xx_to_retry_message(status_code):
    err = requests.HTTPError(response=_fake_response(status_code, {}))
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.get_account", side_effect=err),
    ):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "try again" in (message or "")


@pytest.mark.parametrize("bad_start_date", ["not-a-date", "2026-13-45", "31/01/2026"])
def test_validate_credentials_rejects_invalid_start_date(bad_start_date):
    # Checked before any network call, so no session mock is needed.
    with mock.patch(f"{_SRC}.google_adsense_session") as session_mock:
        ok, message = GoogleAdSenseSource().validate_credentials(_config(start_date=bad_start_date), team_id=1)

    assert ok is False
    assert "YYYY-MM-DD" in (message or "")
    session_mock.assert_not_called()


def test_validate_credentials_accepts_valid_start_date():
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.get_account", return_value={"state": "READY"}),
    ):
        ok, message = GoogleAdSenseSource().validate_credentials(_config(start_date="2026-01-31"), team_id=1)

    assert ok is True
    assert message is None


# ---------------------------------------------------------------------------
# get_oauth_accounts
# ---------------------------------------------------------------------------


def test_get_oauth_accounts_maps_state_to_badge():
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(
            f"{_SRC}.list_accounts",
            return_value=[{"name": "accounts/pub-1", "displayName": "pub-1", "state": "READY"}],
        ),
    ):
        accounts = GoogleAdSenseSource().get_oauth_accounts(integration_id=1, team_id=1)
    assert accounts[0].value == "accounts/pub-1"
    assert accounts[0].display_name == "pub-1"
    assert accounts[0].badges == ("READY",)


def test_get_oauth_accounts_missing_integration_raises_listing_error():
    from posthog.models.integration import Integration

    with (
        mock.patch(f"{_SRC}.google_adsense_session", side_effect=Integration.DoesNotExist()),
        pytest.raises(IntegrationAccountListingError, match="no longer exists"),
    ):
        GoogleAdSenseSource().get_oauth_accounts(integration_id=1, team_id=1)


def test_get_oauth_accounts_quota_error_reports_rate_limiting():
    err = requests.HTTPError(response=_fake_response(403, _QUOTA_BODY))
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.list_accounts", side_effect=err),
        pytest.raises(IntegrationAccountListingError, match="rate limiting"),
    ):
        GoogleAdSenseSource().get_oauth_accounts(integration_id=1, team_id=1)


def test_get_oauth_accounts_refresh_error_raises_listing_error():
    from google.auth.exceptions import RefreshError

    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.list_accounts", side_effect=RefreshError("invalid_scope: Bad Request")),
        pytest.raises(IntegrationAccountListingError),
    ):
        GoogleAdSenseSource().get_oauth_accounts(integration_id=1, team_id=1)


def test_get_oauth_accounts_caches_per_team_and_integration():
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(
            f"{_SRC}.list_accounts",
            return_value=[{"name": "accounts/pub-1", "displayName": "pub-1", "state": "READY"}],
        ) as list_mock,
    ):
        source = GoogleAdSenseSource()
        first = source.get_oauth_accounts(integration_id=1, team_id=1)
        second = source.get_oauth_accounts(integration_id=1, team_id=1)

    assert list_mock.call_count == 1  # second call served from cache
    # A cache hit must return the same type as the uncached path.
    assert second == first
    assert all(isinstance(account, IntegrationAccount) for account in second)
    assert second[0].value == "accounts/pub-1"


def test_get_oauth_accounts_cache_is_scoped_to_team_and_integration():
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(
            f"{_SRC}.list_accounts",
            return_value=[{"name": "accounts/pub-1", "displayName": "pub-1", "state": "READY"}],
        ) as list_mock,
    ):
        source = GoogleAdSenseSource()
        source.get_oauth_accounts(integration_id=1, team_id=1)
        source.get_oauth_accounts(integration_id=1, team_id=1)  # cache hit
        source.get_oauth_accounts(integration_id=2, team_id=1)  # different integration -> miss
        source.get_oauth_accounts(integration_id=1, team_id=2)  # different team -> miss

    assert list_mock.call_count == 3


def test_get_oauth_accounts_does_not_cache_an_empty_result():
    # An empty walk would otherwise freeze the picker empty for the whole TTL.
    with (
        mock.patch(f"{_SRC}.google_adsense_session"),
        mock.patch(f"{_SRC}.list_accounts", return_value=[]) as list_mock,
    ):
        source = GoogleAdSenseSource()
        source.get_oauth_accounts(integration_id=1, team_id=1)
        source.get_oauth_accounts(integration_id=1, team_id=1)

    assert list_mock.call_count == 2
