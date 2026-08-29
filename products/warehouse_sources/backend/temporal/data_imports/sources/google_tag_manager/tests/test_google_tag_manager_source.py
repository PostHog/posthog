from typing import Any, Optional

import pytest
from unittest import mock

import requests
from google.auth.exceptions import RefreshError

from posthog.schema import ReleaseStatus, SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.google_tag_manager import (
    GoogleTagManagerQuotaExceededError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.source import (
    GoogleTagManagerSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.source"


def _config(account_ids: Optional[str] = None) -> GoogleTagManagerSourceConfig:
    return GoogleTagManagerSourceConfig(google_tag_manager_integration_id=1, account_ids=account_ids)


def test_source_type():
    assert GoogleTagManagerSource().source_type == ExternalDataSourceType.GOOGLETAGMANAGER


def test_get_source_config_fields():
    cfg = GoogleTagManagerSource().get_source_config

    field_names = {field.name for field in cfg.fields}
    assert field_names == {"google_tag_manager_integration_id", "account_ids"}
    assert cfg.label == "Google Tag Manager"
    assert cfg.releaseStatus == ReleaseStatus.ALPHA
    assert not cfg.unreleasedSource


def test_get_source_config_oauth_field_declares_required_scope():
    cfg = GoogleTagManagerSource().get_source_config
    oauth_field = next(field for field in cfg.fields if field.name == "google_tag_manager_integration_id")
    assert isinstance(oauth_field, SourceFieldOauthConfig)
    assert oauth_field.kind == "google-tag-manager"
    assert oauth_field.requiredScopes == "https://www.googleapis.com/auth/tagmanager.readonly"


def test_get_schemas_are_full_refresh_only():
    schemas = GoogleTagManagerSource().get_schemas(_config(), team_id=1)

    assert {s.name for s in schemas} == set(ENDPOINTS.keys())
    for schema in schemas:
        # The GTM API has no server-side modification-time filter, so declaring incremental
        # or append support would corrupt syncs with a meaningless watermark.
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []


def test_get_schemas_filters_by_names():
    schemas = GoogleTagManagerSource().get_schemas(_config(), team_id=1, names=["tags", "triggers"])
    assert {s.name for s in schemas} == {"tags", "triggers"}


def test_source_for_pipeline_passes_refresh_token_and_schema():
    source = GoogleTagManagerSource()
    integration = mock.MagicMock()
    integration.refresh_token = "refresh-token"
    inputs = mock.MagicMock()
    inputs.schema_name = "tags"
    inputs.team_id = 7
    config = _config()

    with (
        mock.patch.object(GoogleTagManagerSource, "get_oauth_integration", return_value=integration) as get_integration,
        mock.patch(f"{SOURCE_MODULE}.google_tag_manager_source") as mock_source,
    ):
        source.source_for_pipeline(config, inputs)

    get_integration.assert_called_once_with(1, 7)
    mock_source.assert_called_once_with(config=config, resource_name="tags", refresh_token="refresh-token")


def _validate(config: GoogleTagManagerSourceConfig, probe: Any) -> tuple[bool, str | None]:
    integration = mock.MagicMock()
    integration.refresh_token = "refresh-token"
    with (
        mock.patch.object(GoogleTagManagerSource, "get_oauth_integration", return_value=integration),
        mock.patch(f"{SOURCE_MODULE}.google_tag_manager_session"),
        mock.patch(
            f"{SOURCE_MODULE}.get_accounts_probe",
            **({"side_effect": probe} if isinstance(probe, Exception) else {"return_value": probe}),
        ),
    ):
        return GoogleTagManagerSource().validate_credentials(config, team_id=1)


def _http_error(status_code: int) -> requests.HTTPError:
    response = mock.MagicMock()
    response.status_code = status_code
    return requests.HTTPError(response=response)


def test_validate_credentials_handles_missing_integration():
    with mock.patch.object(
        GoogleTagManagerSource, "get_oauth_integration", side_effect=ValueError("Integration not found: 1")
    ):
        ok, message = GoogleTagManagerSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "no longer exists" in (message or "")
    assert "Integration not found" not in (message or "")


@pytest.mark.parametrize(
    "status_code,expected_substring",
    [
        (401, "rejected the credentials"),
        (403, "rejected the credentials"),
        (500, "Failed to list Google Tag Manager accounts"),
    ],
)
def test_validate_credentials_maps_http_errors(status_code, expected_substring):
    ok, message = _validate(_config(), _http_error(status_code))

    assert ok is False
    assert expected_substring in (message or "")


def test_validate_credentials_maps_token_refresh_error():
    refresh_error = RefreshError("invalid_grant: Bad Request", {"error": "invalid_grant"})
    ok, message = _validate(_config(), refresh_error)

    assert ok is False
    assert "reconnect your Google" in (message or "")
    assert "invalid_grant" not in (message or "")


def test_validate_credentials_rejects_empty_account_list():
    ok, message = _validate(_config(), {"account": []})

    assert ok is False
    assert "doesn't have access to any Tag Manager accounts" in (message or "")


def test_validate_credentials_rejects_inaccessible_account_ids():
    payload = {"account": [{"accountId": "1"}, {"accountId": "2"}]}
    ok, message = _validate(_config(account_ids="2, 3, 4"), payload)

    assert ok is False
    assert "3, 4" in (message or "")


def test_validate_credentials_skips_filter_check_when_paginated():
    # With more account pages the missing IDs may be on a later page, so the probe must not
    # reject the filter from a partial listing.
    payload = {"account": [{"accountId": "1"}], "nextPageToken": "t1"}
    ok, message = _validate(_config(account_ids="3"), payload)

    assert ok is True
    assert message is None


def test_validate_credentials_succeeds_with_matching_filter():
    payload = {"account": [{"accountId": "1"}, {"accountId": "2"}]}
    ok, message = _validate(_config(account_ids="1"), payload)

    assert ok is True
    assert message is None


def test_non_retryable_errors_match_revoked_refresh_token():
    observed_error = str(RefreshError("invalid_grant: Bad Request", {"error": "invalid_grant"}))
    assert error_message_matches(observed_error, GoogleTagManagerSource().get_non_retryable_errors())


def test_retryable_errors_cover_exhausted_quota():
    error = GoogleTagManagerQuotaExceededError(
        "Google Tag Manager API quota still exhausted after 5 retries (retryable)"
    )
    patterns = GoogleTagManagerSource().get_retryable_errors()
    assert any(pattern in str(error) for pattern in patterns)
