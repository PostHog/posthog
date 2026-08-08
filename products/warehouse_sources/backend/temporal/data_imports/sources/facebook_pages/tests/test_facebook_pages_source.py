from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldOauthAccountSelectConfig, SourceFieldOauthConfig

from posthog.models.integration import FACEBOOK_PAGES_SCOPE

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.facebook_pages import (
    AUTH_ERROR_PREFIX,
    INVALID_PAGE_ID_ERROR,
    PERMISSION_ERROR_PREFIX,
    TOKEN_REFRESH_ERROR_MESSAGE,
    FacebookPagesAuthError,
    FacebookPagesResumeConfig,
    FacebookPagesRetryableError,
    FacebookPagesTokenRefreshError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.settings import (
    DEFAULT_API_VERSION,
    ENDPOINTS,
    FACEBOOK_PAGES_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.source import FacebookPagesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.facebookpages import (
    FacebookPagesSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.source"

USER_TOKEN = "user-token"


class TestFacebookPagesSource:
    def setup_method(self) -> None:
        self.source = FacebookPagesSource()
        self.team_id = 123
        self.config = FacebookPagesSourceConfig(page_id="123456789012345", facebook_pages_integration_id=7)

    def _with_token(self, token: str = USER_TOKEN) -> Any:
        return mock.patch.object(FacebookPagesSource, "_access_token", return_value=token)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FACEBOOKPAGES

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "FacebookPages"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/facebook_pages.png"
        assert [f.name for f in config.fields] == ["facebook_pages_integration_id", "page_id"]

    def test_oauth_field_requests_the_page_scopes(self) -> None:
        oauth_field = self.source.get_source_config.fields[0]

        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.kind == "facebook-pages"
        assert oauth_field.required is True
        # Declared so the frontend can warn when an older grant is missing one of them.
        assert oauth_field.requiredScopes == FACEBOOK_PAGES_SCOPE

    def test_page_is_picked_from_the_connected_account(self) -> None:
        page_field = self.source.get_source_config.fields[1]

        assert isinstance(page_field, SourceFieldOauthAccountSelectConfig)
        assert page_field.integrationField == "facebook_pages_integration_id"
        assert page_field.integrationKind == "facebook-pages"
        assert page_field.required is True

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == (DEFAULT_API_VERSION,)
        assert self.source.default_version == DEFAULT_API_VERSION
        assert (self.source.api_docs_url or "").startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so public docs can render the tables.
        assert self.source.lists_tables_without_credentials is True

    def test_page_id_forces_secret_reentry_on_change(self) -> None:
        # page_id retargets the connected token at another Page, so changing it must require
        # re-entering the secrets — otherwise an editor who can't read the token could sync a
        # different Page the token happens to have access to.
        assert self.source.connection_host_fields == ["page_id"]

    @pytest.mark.parametrize(
        "expected_key",
        [
            AUTH_ERROR_PREFIX,
            PERMISSION_ERROR_PREFIX,
            TOKEN_REFRESH_ERROR_MESSAGE,
            INVALID_PAGE_ID_ERROR,
            "Integration not found",
        ],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental, incremental_field",
        [
            ("page", False, None),
            ("posts", True, "created_time"),
            ("videos", True, "created_time"),
            ("page_insights", True, "end_time"),
        ],
    )
    def test_schema_sync_modes(self, endpoint: str, incremental: bool, incremental_field: str | None) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]

        assert schema.supports_incremental is incremental
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ([incremental_field] if incremental_field else [])

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["posts", "nope"])

        assert [s.name for s in schemas] == ["posts"]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        assert descriptions is CANONICAL_DESCRIPTIONS

    @pytest.mark.parametrize("endpoint", list(FACEBOOK_PAGES_ENDPOINTS))
    def test_canonical_descriptions_cover_the_primary_keys(self, endpoint: str) -> None:
        # The primary key columns are the ones the AI agent most needs described.
        columns = self.source.get_canonical_descriptions()[endpoint].get("columns", {})
        primary_keys = FACEBOOK_PAGES_ENDPOINTS[endpoint].primary_keys or []

        assert set(primary_keys) <= set(columns)

    @pytest.mark.parametrize("page_id, integration_id", [("123", 0), ("", 7)])
    def test_validate_credentials_requires_both_the_integration_and_a_page(
        self, page_id: str, integration_id: int
    ) -> None:
        config = FacebookPagesSourceConfig(page_id=page_id, facebook_pages_integration_id=integration_id)

        ok, error = self.source.validate_credentials(config, self.team_id)

        assert ok is False
        assert error

    @pytest.mark.parametrize(
        "raised", [ValueError("Integration not found: 7"), FacebookPagesTokenRefreshError(TOKEN_REFRESH_ERROR_MESSAGE)]
    )
    def test_validate_credentials_reports_a_broken_integration(self, raised: Exception) -> None:
        with mock.patch.object(FacebookPagesSource, "_access_token", side_effect=raised):
            ok, error = self.source.validate_credentials(self.config, self.team_id)

        assert ok is False
        assert error == str(raised)

    @mock.patch(f"{SOURCE_MODULE}.validate_facebook_pages_credentials", return_value=(True, None))
    def test_validate_credentials_probes_with_the_integration_token(self, mock_validate: mock.MagicMock) -> None:
        with self._with_token():
            assert self.source.validate_credentials(self.config, self.team_id, schema_name="posts") == (True, None)

        mock_validate.assert_called_once_with(
            page_id=self.config.page_id,
            access_token=USER_TOKEN,
            api_version=DEFAULT_API_VERSION,
            schema_name="posts",
        )

    @mock.patch(f"{SOURCE_MODULE}.list_pages")
    def test_get_oauth_accounts_maps_the_pages_the_user_administers(self, mock_list: mock.MagicMock) -> None:
        mock_list.return_value = [{"id": "1", "name": "PostHog", "category": "Software"}, {"id": "2"}]

        with self._with_token():
            accounts = self.source.get_oauth_accounts(7, self.team_id)

        assert [(a.value, a.display_name, a.badges) for a in accounts] == [
            ("1", "PostHog", ("Software",)),
            ("2", "Unnamed Page", ()),
        ]

    @pytest.mark.parametrize(
        "raised", [ValueError("Integration not found: 7"), FacebookPagesTokenRefreshError(TOKEN_REFRESH_ERROR_MESSAGE)]
    )
    def test_get_oauth_accounts_surfaces_a_broken_integration(self, raised: Exception) -> None:
        with mock.patch.object(FacebookPagesSource, "_access_token", side_effect=raised):
            with pytest.raises(IntegrationAccountListingError):
                self.source.get_oauth_accounts(7, self.team_id)

    @pytest.mark.parametrize("raised", [FacebookPagesAuthError("nope"), FacebookPagesRetryableError("throttled")])
    @mock.patch(f"{SOURCE_MODULE}.list_pages")
    def test_get_oauth_accounts_turns_graph_failures_into_actionable_errors(
        self, mock_list: mock.MagicMock, raised: Exception
    ) -> None:
        # These are the customer's to fix or Meta's to recover from, so they must not escape as a 500.
        mock_list.side_effect = raised

        with self._with_token(), pytest.raises(IntegrationAccountListingError):
            self.source.get_oauth_accounts(7, self.team_id)

    def test_get_resumable_source_manager(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FacebookPagesResumeConfig

    @mock.patch(f"{SOURCE_MODULE}.facebook_pages_source")
    def test_source_for_pipeline_plumbs_the_integration_token(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.api_version = None
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00+0000"
        manager = mock.MagicMock()

        with self._with_token() as mock_token:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_token.assert_called_once_with(self.config.facebook_pages_integration_id, self.team_id)
        kwargs: dict[str, Any] = dict(mock_source.call_args.kwargs)
        assert kwargs["page_id"] == self.config.page_id
        assert kwargs["access_token"] == USER_TOKEN
        assert kwargs["endpoint"] == "posts"
        assert kwargs["api_version"] == DEFAULT_API_VERSION
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00+0000"

    @mock.patch(f"{SOURCE_MODULE}.facebook_pages_source")
    def test_watermark_is_withheld_when_not_syncing_incrementally(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.api_version = None
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00+0000"

        with self._with_token():
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch(f"{SOURCE_MODULE}.facebook_pages_source")
    def test_pinned_api_version_is_honored(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.api_version = "v21.0"
        inputs.should_use_incremental_field = False

        with self._with_token():
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["api_version"] == "v21.0"
