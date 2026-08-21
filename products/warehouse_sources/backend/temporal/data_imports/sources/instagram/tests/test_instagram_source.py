import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instagram import (
    InstagramSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram import (
    InstagramAuthError,
    InstagramRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import INSTAGRAM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source import InstagramSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source"
ACCOUNT_ID = "17841400000000000"


class TestInstagramSource:
    def setup_method(self) -> None:
        self.source = InstagramSource()
        self.team_id = 1
        self.config = InstagramSourceConfig(instagram_integration_id=7, instagram_account_id=ACCOUNT_ID)

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

    # Each supported version's pin must reach the request layer verbatim, so a source pinned to
    # an older Graph API version keeps hitting its own path once v26.0 is the default.
