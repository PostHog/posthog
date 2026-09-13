from typing import Any

import pytest
from unittest import mock

import structlog

from posthog.schema import SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instagram import (
    InstagramSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram import (
    AUTH_ERROR_PREFIX,
    PERMISSION_ERROR_PREFIX,
    InstagramAuthError,
    InstagramResumeConfig,
    InstagramRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import INSTAGRAM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source import InstagramSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source"
ACCOUNT_ID = "17841400000000000"


def _inputs(schema_name: str = "media", **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": structlog.get_logger("instagram-tests"),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestInstagramSource:
    def setup_method(self) -> None:
        self.source = InstagramSource()
        self.team_id = 1
        self.config = InstagramSourceConfig(instagram_integration_id=7, instagram_account_id=ACCOUNT_ID)

    def test_the_connection_is_a_posthog_owned_oauth_app(self) -> None:
        integration = next(f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldOauthConfig))

        assert integration.kind == "instagram"
        assert integration.required is True
        # The insights and comments tables are unreadable without these, so the frontend has to
        # be able to tell the user which grant is missing.
        assert integration.requiredScopes is not None
        assert set(integration.requiredScopes.split(" ")) == {
            "instagram_basic",
            "instagram_manage_insights",
            "instagram_manage_comments",
            "pages_show_list",
            "pages_read_engagement",
        }

    def test_the_graph_api_version_is_pinned_to_something_the_code_calls(self) -> None:
        assert self.source.default_version in self.source.supported_versions
        # New sources land on the newest Graph API version; an unpinned row resolves to it too.
        assert self.source.resolve_api_version(None) == "v26.0"
        # An existing pin is honored verbatim so older sources keep hitting their own version path.
        assert self.source.resolve_api_version("v23.0") == "v23.0"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    def test_fan_out_tables_key_on_the_parent_so_rows_stay_unique_table_wide(self) -> None:
        assert INSTAGRAM_ENDPOINTS["media_comments"].primary_keys == ["media_id", "id"]
        assert INSTAGRAM_ENDPOINTS["media_insights"].primary_keys == ["media_id", "metric"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            f"{AUTH_ERROR_PREFIX}: status=400, code=190, message=Session has expired",
            f"{PERMISSION_ERROR_PREFIX}: status=400, code=10, message=Application does not have permission",
            "Failed to refresh the Instagram connection",
            "Integration not found: 7",
        ],
    )
    def test_auth_and_scope_failures_stop_the_source_instead_of_retrying(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_a_throttling_error_is_left_retryable(self) -> None:
        observed_error = "Instagram API error (retryable): status=429, code=4, message=rate limited"

        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_validate_credentials_uses_the_connection_token_and_the_chosen_account(self) -> None:
        with (
            mock.patch.object(InstagramSource, "_access_token", return_value="refreshed-token"),
            mock.patch(f"{SOURCE_MODULE}.validate_instagram_credentials", return_value=(True, None)) as validate,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        assert validate.call_args.kwargs["access_token"] == "refreshed-token"
        assert validate.call_args.kwargs["instagram_account_id"] == ACCOUNT_ID
        assert validate.call_args.kwargs["api_version"] == "v26.0"

    def test_validate_credentials_fails_cleanly_when_the_connection_is_gone(self) -> None:
        with (
            mock.patch.object(InstagramSource, "_access_token", side_effect=ValueError("Integration not found: 7")),
            mock.patch(f"{SOURCE_MODULE}.validate_instagram_credentials") as validate,
        ):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None and "Connect an Instagram account" in message
        validate.assert_not_called()

    def test_validate_credentials_surfaces_the_failure_message(self) -> None:
        with (
            mock.patch.object(InstagramSource, "_access_token", return_value="tok"),
            mock.patch(f"{SOURCE_MODULE}.validate_instagram_credentials", return_value=(False, "bad token")),
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == (False, "bad token")

    def test_the_account_picker_lists_the_professional_accounts_the_connection_can_reach(self) -> None:
        listed = [
            {"id": ACCOUNT_ID, "username": "posthog", "name": "PostHog", "page_name": "PostHog page"},
            {"id": "17841999", "username": None, "name": None, "page_name": "Unnamed page"},
        ]

        with (
            mock.patch.object(InstagramSource, "_access_token", return_value="tok"),
            mock.patch(f"{SOURCE_MODULE}.list_professional_accounts", return_value=listed),
        ):
            accounts = self.source.get_oauth_accounts(7, self.team_id)

        assert [(account.value, account.display_name, account.secondary_text) for account in accounts] == [
            (ACCOUNT_ID, "posthog", "PostHog page"),
            ("17841999", "Instagram account", "Unnamed page"),
        ]

    @pytest.mark.parametrize(
        "raised,expected_fragment",
        [
            (InstagramAuthError("nope"), "Reconnect your Instagram account"),
            (InstagramRetryableError("throttled"), "try again in a few minutes"),
        ],
    )
    def test_a_failing_account_listing_is_reported_as_something_the_user_can_act_on(
        self, raised: Exception, expected_fragment: str
    ) -> None:
        with (
            mock.patch.object(InstagramSource, "_access_token", return_value="tok"),
            mock.patch(f"{SOURCE_MODULE}.list_professional_accounts", side_effect=raised),
        ):
            with pytest.raises(IntegrationAccountListingError, match=expected_fragment):
                self.source.get_oauth_accounts(7, self.team_id)

    def test_the_resume_manager_is_isolated_per_table(self) -> None:
        media = self.source.get_resumable_source_manager(_inputs("media"))
        comments = self.source.get_resumable_source_manager(_inputs("media_comments"))

        assert isinstance(media, ResumableSourceManager)
        assert media._data_class is InstagramResumeConfig
        # Each table checkpoints a URL built for its own edge, so the Redis slots differ.
        assert media._key != comments._key

    # Each supported version's pin must reach the request layer verbatim, so a source pinned to
    # an older Graph API version keeps hitting its own path once v26.0 is the default.
    @pytest.mark.parametrize("pinned_version", ["v22.0", "v23.0", "v26.0"])
    def test_source_for_pipeline_syncs_with_the_connection_token(self, pinned_version: str) -> None:
        config = InstagramSourceConfig(
            instagram_integration_id=7, instagram_account_id=ACCOUNT_ID, start_date="2024-01-01"
        )
        inputs = _inputs(
            "media",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-01T00:00:00+0000",
            api_version=pinned_version,
        )

        with (
            mock.patch.object(InstagramSource, "_access_token", return_value="refreshed-token"),
            mock.patch(f"{SOURCE_MODULE}.instagram_source") as build_source,
        ):
            self.source.source_for_pipeline(config, self.source.get_resumable_source_manager(inputs), inputs)

        kwargs = build_source.call_args.kwargs
        assert kwargs["access_token"] == "refreshed-token"
        assert kwargs["endpoint"] == "media"
        assert kwargs["api_version"] == pinned_version
        assert kwargs["instagram_account_id"] == ACCOUNT_ID
        assert kwargs["start_date"] == "2024-01-01"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01T00:00:00+0000"

    def test_a_full_refresh_run_never_forwards_a_watermark(self) -> None:
        inputs = _inputs("media", should_use_incremental_field=False, db_incremental_field_last_value="2024-06-01")

        with (
            mock.patch.object(InstagramSource, "_access_token", return_value="tok"),
            mock.patch(f"{SOURCE_MODULE}.instagram_source") as build_source,
        ):
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)

        assert build_source.call_args.kwargs["db_incremental_field_last_value"] is None
