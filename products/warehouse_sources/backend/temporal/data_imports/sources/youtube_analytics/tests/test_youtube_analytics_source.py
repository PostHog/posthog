from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldOauthConfig

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubeanalytics import (
    YouTubeAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.settings import (
    ANALYTICS_SCOPE,
    CHANNEL_DAILY,
    DEMOGRAPHICS,
    ENDPOINTS,
    REVISION_LOOKBACK_SECONDS,
    TOP_VIDEOS,
    YOUTUBE_READONLY_SCOPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.source import (
    YouTubeAnalyticsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.youtube_analytics import (
    YouTubeAnalyticsAuthError,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.source"
INTEGRATION_ID = 42


def _config(**overrides: Any) -> YouTubeAnalyticsSourceConfig:
    values: dict[str, Any] = {
        "youtube_analytics_integration_id": INTEGRATION_ID,
        "channel_id": "UC123",
        "start_date": None,
    }
    values.update(overrides)
    return YouTubeAnalyticsSourceConfig(**values)


def _integration(access_token: str | None = "access-token", errors: str = "") -> mock.MagicMock:
    integration = mock.MagicMock()
    integration.access_token = access_token
    integration.errors = errors
    return integration


def _http_error(status: int) -> requests.HTTPError:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


class TestYouTubeAnalyticsSource:
    def setup_method(self) -> None:
        self.source = YouTubeAnalyticsSource()
        self.team_id = 123
        self.config = _config()

    def _patch_integration(self, integration: mock.MagicMock, expired: bool = False) -> Any:
        """Stand in for the DB-backed integration and its OAuth refresh."""
        oauth = mock.MagicMock()
        oauth.access_token_expired.return_value = expired
        return (
            mock.patch.object(YouTubeAnalyticsSource, "get_oauth_integration", return_value=integration),
            mock.patch(f"{MODULE}.OauthIntegration", return_value=oauth),
            oauth,
        )

    def test_source_config_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        # Dropping the flag would expose the source to every project, not just the ones opted in.
        assert config.featureFlag == "dwh_youtube_analytics"
        assert config.iconPath == "/static/services/youtube_analytics.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/youtube-analytics"

    def test_authentication_is_a_posthog_owned_oauth_app(self) -> None:
        fields = self.source.get_source_config.fields
        oauth = next(f for f in fields if isinstance(f, SourceFieldOauthConfig))

        assert oauth.name == "youtube_analytics_integration_id"
        assert oauth.kind == "youtube-analytics"
        assert oauth.required is True
        # The frontend warns on a missing grant, so both scopes the source calls must be listed.
        assert oauth.requiredScopes is not None
        assert set(oauth.requiredScopes.split()) == {ANALYTICS_SCOPE, YOUTUBE_READONLY_SCOPE}

    def test_no_field_asks_the_user_for_oauth_credentials(self) -> None:
        # Users must never be asked to register their own Google app and paste a refresh token.
        inputs = [f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)]

        assert [f.name for f in inputs] == ["start_date"]
        assert inputs[0].type == SourceFieldInputConfigType.TEXT
        assert inputs[0].required is False

    def test_pins_the_vendor_api_version_it_calls(self) -> None:
        assert self.source.supported_versions == ("v2",)
        assert self.source.default_version == "v2"
        assert (self.source.api_docs_url or "").startswith("https://")

    def test_get_schemas_returns_every_report(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_report_is_incremental_on_day(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert schema.supports_append is False
        assert [field["field"] for field in schema.incremental_fields] == ["day"]
        # YouTube restates recent days, so incremental runs must re-read a trailing window.
        assert schema.default_incremental_lookback_seconds == REVISION_LOOKBACK_SECONDS

    @parameterized.expand(
        [
            (CHANNEL_DAILY, ["day"]),
            (TOP_VIDEOS, ["day", "video"]),
            (DEMOGRAPHICS, ["day", "ageGroup", "gender"]),
        ]
    )
    def test_primary_keys_include_every_breakdown_dimension(self, endpoint: str, expected: list[str]) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.detected_primary_keys == expected

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=[TOP_VIDEOS])
        assert [schema.name for schema in schemas] == [TOP_VIDEOS]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_lists_tables_without_credentials(self) -> None:
        # The report catalog is static, so public docs can render it without connecting.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            ("401 Client Error",),
            ("403 Client Error: Forbidden for url: https://youtubeanalytics.googleapis.com",),
            ("Integration not found",),
        ]
    )
    def test_auth_failures_are_non_retryable(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    @parameterized.expand(
        [
            ("fresh_token_is_reused", False, False, 0),
            ("stale_token_is_refreshed", True, False, 1),
            ("forced_refresh_always_mints", False, True, 1),
        ]
    )
    def test_access_token_refreshes_only_when_needed(
        self, _name: str, expired: bool, force_refresh: bool, refresh_calls: int
    ) -> None:
        get_integration, oauth_cls, oauth = self._patch_integration(_integration(), expired=expired)

        with get_integration, oauth_cls:
            token = self.source.access_token(INTEGRATION_ID, self.team_id, force_refresh=force_refresh)

        assert token == "access-token"
        assert oauth.refresh_access_token.call_count == refresh_calls

    @parameterized.expand(
        [
            ("refresh_failed", "access-token", ERROR_TOKEN_REFRESH_FAILED),
            ("no_token_stored", None, ""),
        ]
    )
    def test_unusable_credentials_raise_instead_of_syncing_with_no_token(
        self, _name: str, access_token: str | None, errors: str
    ) -> None:
        get_integration, oauth_cls, _ = self._patch_integration(
            _integration(access_token=access_token, errors=errors), expired=True
        )

        with get_integration, oauth_cls, pytest.raises(YouTubeAnalyticsAuthError):
            self.source.access_token(INTEGRATION_ID, self.team_id)

    def test_get_oauth_accounts_lists_the_connected_accounts_channels(self) -> None:
        get_integration, oauth_cls, _ = self._patch_integration(_integration())
        channels = [
            {"id": "UC123", "snippet": {"title": "Acme", "customUrl": "@acme"}},
            {"id": "UC456", "snippet": {}},
        ]

        with get_integration, oauth_cls, mock.patch(f"{MODULE}.list_channels", return_value=channels):
            accounts = self.source.get_oauth_accounts(INTEGRATION_ID, self.team_id)

        assert [(a.value, a.display_name, a.secondary_text) for a in accounts] == [
            ("UC123", "Acme", "@acme"),
            ("UC456", "UC456", None),
        ]

    @parameterized.expand(
        [
            ("unauthorized", 401, "reconnect"),
            ("forbidden", 403, "reconnect"),
            ("rate_limited", 429, "try again"),
            ("server_error", 503, "try again"),
        ]
    )
    def test_get_oauth_accounts_surfaces_actionable_listing_failures(
        self, _name: str, status: int, fragment: str
    ) -> None:
        get_integration, oauth_cls, _ = self._patch_integration(_integration())

        with (
            get_integration,
            oauth_cls,
            mock.patch(f"{MODULE}.list_channels", side_effect=_http_error(status)),
            pytest.raises(IntegrationAccountListingError) as error,
        ):
            self.source.get_oauth_accounts(INTEGRATION_ID, self.team_id)

        assert fragment in str(error.value).lower()

    def test_get_oauth_accounts_on_a_deleted_integration_asks_for_a_reconnect(self) -> None:
        with (
            mock.patch.object(
                YouTubeAnalyticsSource, "get_oauth_integration", side_effect=ValueError("Integration not found: 42")
            ),
            pytest.raises(IntegrationAccountListingError),
        ):
            self.source.get_oauth_accounts(INTEGRATION_ID, self.team_id)

    def test_validate_credentials_without_an_integration(self) -> None:
        is_valid, error = self.source.validate_credentials(_config(youtube_analytics_integration_id=0), self.team_id)

        assert is_valid is False
        assert error is not None and "Connect a Google account" in error

    @parameterized.expand(
        [
            ("valid", (True, None), True, None),
            ("rejected", (False, "Google rejected the connected account's credentials."), False, "Google rejected"),
        ]
    )
    def test_validate_credentials_probes_with_the_integration_token(
        self, _name: str, mock_return: tuple[bool, str | None], expected_valid: bool, expected_fragment: str | None
    ) -> None:
        get_integration, oauth_cls, _ = self._patch_integration(_integration())

        with get_integration, oauth_cls, mock.patch(f"{MODULE}.validate_youtube_analytics_credentials") as validate:
            validate.return_value = mock_return
            is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_fragment in error
        validate.assert_called_once_with(
            access_token="access-token", channel_id="UC123", start_date=None, api_version="v2"
        )

    def test_validate_credentials_reports_an_unusable_connection(self) -> None:
        get_integration, oauth_cls, _ = self._patch_integration(_integration(access_token=None), expired=True)

        with get_integration, oauth_cls:
            is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error is not None and "reconnect" in error.lower()

    def _inputs(self, **overrides: Any) -> SourceInputs:
        values: dict[str, Any] = {
            "schema_name": CHANNEL_DAILY,
            "team_id": self.team_id,
            "job_id": "job-1",
            "logger": mock.MagicMock(),
            "api_version": None,
            "should_use_incremental_field": True,
            "incremental_field": "day",
            "db_incremental_field_last_value": "2026-07-01",
        }
        values.update(overrides)
        return cast(SourceInputs, SimpleNamespace(**values))

    def test_source_for_pipeline_syncs_with_the_integration_token(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = self._inputs()
        get_integration, oauth_cls, _ = self._patch_integration(_integration())

        with get_integration, oauth_cls, mock.patch(f"{MODULE}.youtube_analytics_source") as mock_source:
            response = self.source.source_for_pipeline(_config(start_date="2026-01-01"), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "access-token"
        assert kwargs["channel_id"] == "UC123"
        assert kwargs["start_date"] == "2026-01-01"
        assert kwargs["endpoint"] == CHANNEL_DAILY
        assert kwargs["api_version"] == "v2"
        assert kwargs["logger"] is inputs.logger
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-01"
        assert response is mock_source.return_value

    def test_source_for_pipeline_hands_the_sync_a_forced_token_refresh(self) -> None:
        # Google tokens expire mid-backfill, so the sync must be able to re-mint one.
        manager = mock.MagicMock(spec=ResumableSourceManager)
        get_integration, oauth_cls, oauth = self._patch_integration(_integration())

        with get_integration, oauth_cls, mock.patch(f"{MODULE}.youtube_analytics_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, self._inputs())
            assert oauth.refresh_access_token.call_count == 0

            assert mock_source.call_args.kwargs["refresh_access_token"]() == "access-token"
            assert oauth.refresh_access_token.call_count == 1

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        get_integration, oauth_cls, _ = self._patch_integration(_integration())

        with get_integration, oauth_cls, mock.patch(f"{MODULE}.youtube_analytics_source") as mock_source:
            self.source.source_for_pipeline(
                self.config, manager, self._inputs(schema_name=TOP_VIDEOS, should_use_incremental_field=False)
            )

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_honors_a_pinned_api_version(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        get_integration, oauth_cls, _ = self._patch_integration(_integration())

        with get_integration, oauth_cls, mock.patch(f"{MODULE}.youtube_analytics_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, self._inputs(api_version="v3"))

        assert mock_source.call_args.kwargs["api_version"] == "v3"
