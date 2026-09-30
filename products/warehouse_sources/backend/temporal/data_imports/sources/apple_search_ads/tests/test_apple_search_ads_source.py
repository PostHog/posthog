from datetime import date
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldCredentialAccountSelectConfig,
    SourceFieldInputConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads import (
    AppleAdAccount,
    AppleSearchAdsAuthError,
    AppleSearchAdsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_ADS_API_VERSION_V1,
    APPLE_SEARCH_ADS_API_VERSION_V5,
    ENDPOINTS,
    REPORT_LOOKBACK_SECONDS,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.source import (
    AppleSearchAdsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    VersionDeprecation,
    error_message_matches,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applesearchads import (
    AppleSearchAdsSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.source"

_PLATFORM_ENDPOINTS = endpoints_for_version(APPLE_ADS_API_VERSION_V1)
REPORT_ENDPOINTS = tuple(name for name, config in _PLATFORM_ENDPOINTS.items() if config.partition_key)
ENTITY_ENDPOINTS = tuple(name for name, config in _PLATFORM_ENDPOINTS.items() if not config.partition_key)


class TestAppleSearchAdsSource:
    def setup_method(self) -> None:
        self.source = AppleSearchAdsSource()
        self.team_id = 123
        self.config = AppleSearchAdsSourceConfig(
            client_id="SEARCHADS.client",
            apple_team_id="SEARCHADS.team",
            key_id="key-1",
            private_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            ad_account_id="123456789",
            start_date="2026-06-01",
        )

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == (APPLE_SEARCH_ADS_API_VERSION_V5, APPLE_ADS_API_VERSION_V1)
        assert self.source.default_version == APPLE_ADS_API_VERSION_V1
        assert self.source.api_docs_url.startswith("https://")

    def test_the_retired_api_version_carries_apples_sunset_date(self) -> None:
        # Drives the in-product deprecation warning, so the date has to be Apple's.
        assert self.source.deprecated_versions == (
            VersionDeprecation(version=APPLE_SEARCH_ADS_API_VERSION_V5, sunset_at=date(2027, 1, 26)),
        )

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` walks a static catalog, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_force_secret_reentry_on_account_or_org_change(self) -> None:
        # The stored private key is sent against whichever ad account (Platform API) or
        # organization (v5) is configured, so changing either must force the editor to re-enter
        # the key — otherwise a retarget silently reuses the credential against a different Apple
        # account.
        assert self.source.connection_host_fields == ["ad_account_id", "org_id"]

    @parameterized.expand([(APPLE_SEARCH_ADS_API_VERSION_V5,), (APPLE_ADS_API_VERSION_V1,)])
    def test_get_schemas_covers_the_same_endpoint_catalog_on_every_version(self, api_version: str) -> None:
        # A repinned source must keep every table it had, so the table set cannot vary.
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.description for schema in schemas)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns", "campaign_report"])

        assert {schema.name for schema in schemas} == {"campaigns", "campaign_report"}

    @parameterized.expand([(endpoint,) for endpoint in REPORT_ENDPOINTS])
    def test_report_tables_are_incremental_on_date_with_a_lookback(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["date"]
        assert schema.default_incremental_lookback_seconds == REPORT_LOOKBACK_SECONDS
        # The lookback re-reads already-imported days, so appending would duplicate them.
        assert schema.supports_append is False

    @parameterized.expand([(endpoint,) for endpoint in ENTITY_ENDPOINTS])
    def test_entity_tables_are_full_refresh_only(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        # Apple's entity endpoints have no updated-since filter, so there is nothing to track.
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []
        assert schema.default_incremental_lookback_seconds is None

    @parameterized.expand(
        [
            ("platform_unauthorized", 401, "api.ads.apple.com"),
            ("platform_forbidden", 403, "api.ads.apple.com"),
            ("legacy_bad_request", 400, "api.searchads.apple.com"),
            ("legacy_unauthorized", 401, "api.searchads.apple.com"),
            ("legacy_forbidden", 403, "api.searchads.apple.com"),
        ]
    )
    def test_non_retryable_errors_cover_auth_failures_on_both_hosts(self, _name: str, status: int, host: str) -> None:
        errors = self.source.get_non_retryable_errors()

        assert any(str(status) in key and host in key for key in errors)
        assert all(message for message in errors.values())

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.searchads.apple.com/api/v5/reports",
            ),
            (
                "service_unavailable",
                "503 Server Error: Service Temporarily Unavailable for url: https://api.searchads.apple.com/api/v5/targetingkeywords/find",
            ),
            ("bad_gateway", "502 Server Error: Bad Gateway for url: https://api.ads.apple.com/v1/campaigns"),
            ("gateway_timeout", "504 Server Error: Gateway Timeout for url: https://api.ads.apple.com/v1/reports"),
        ]
    )
    def test_transient_api_statuses_are_retryable(self, _name: str, error_msg: str) -> None:
        # These are the statuses the transport already retries; once exhausted they must stay
        # retryable (and out of the non-retryable set) so a self-recovering blip isn't reported
        # as an unclassified error and the sync isn't disabled.
        assert error_message_matches(error_msg, self.source.get_retryable_errors())
        assert not error_message_matches(error_msg, self.source.get_non_retryable_errors().keys())

    def test_get_resumable_source_manager_is_namespaced_per_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaign_report"

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppleSearchAdsResumeConfig
        # Entity and report checkpoints have incompatible shapes, so they must not share a slot.
        assert manager._namespace == "campaign_report"

    @parameterized.expand([(None, APPLE_ADS_API_VERSION_V1), ("v5", APPLE_SEARCH_ADS_API_VERSION_V5)])
    def test_source_for_pipeline_plumbs_the_resolved_version(self, pinned: str | None, expected: str) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaign_report"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-05-01"
        inputs.api_version = pinned
        manager = mock.MagicMock()

        with mock.patch(f"{SOURCE_MODULE}.apple_search_ads_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = cast("dict[str, Any]", mock_source.call_args.kwargs)
        assert kwargs["endpoint"] == "campaign_report"
        # An unset pin resolves to the current default, a stored one is honored verbatim.
        assert kwargs["api_version"] == expected
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-05-01"
        assert kwargs["start_date"] == "2026-06-01"

    def test_both_context_ids_reach_the_credentials(self) -> None:
        # Which one a sync needs follows the version pin, so the form collects either and the
        # request layer picks.
        config = AppleSearchAdsSourceConfig(
            client_id="SEARCHADS.client",
            apple_team_id="SEARCHADS.team",
            key_id="key-1",
            private_key="pem",
            ad_account_id="123456789",
            org_id="555",
        )

        credentials = self.source._credentials(config)

        assert (credentials.ad_account_id, credentials.org_id) == ("123456789", "555")

    def test_the_field_caption_and_step_five_describe_the_same_flow(self) -> None:
        # Two surfaces describe how someone gets their ad account id, and nothing renders them
        # together, so one can be rewritten while the other keeps naming a flow that is gone.
        config = self.source.get_source_config
        field_caption = next(
            field.caption
            for field in config.fields
            if isinstance(field, SourceFieldCredentialAccountSelectConfig) and field.name == "ad_account_id"
        )
        assert field_caption is not None
        assert config.caption is not None
        step_five = next(line for line in config.caption.splitlines() if line.startswith("5."))

        for text in (field_caption, step_five):
            # Both name the picker and the manual fallback, and neither still tells anyone to
            # connect with the field blank.
            assert "list" in text
            assert "v1/acls" in text
            assert "blank" not in text

    def test_the_connect_form_does_not_require_either_context_id(self) -> None:
        # `required` cannot express "depends on the version pin", so `validate_credentials`
        # enforces whichever one applies instead.
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig | SourceFieldCredentialAccountSelectConfig)
        }

        assert fields["ad_account_id"].required is False
        assert fields["org_id"].required is False

    def test_credential_accounts_map_apples_acl_onto_the_shared_picker_shape(self) -> None:
        # Apple shows the ad account id nowhere in its UI, so the ACL read is the only way a user
        # gets one. An account with no name falls back to its id rather than rendering "None".
        with (
            mock.patch(f"{SOURCE_MODULE}.AppleSearchAdsClient") as mock_client,
            mock.patch(f"{SOURCE_MODULE}.readable_ad_accounts") as mock_accounts,
        ):
            mock_accounts.return_value = [
                AppleAdAccount(id="1111111", name="Example Retail"),
                AppleAdAccount(id="2222222", name=None),
            ]

            accounts = self.source.get_credential_accounts(self.config, self.team_id)

        mock_client.return_value.authenticate.assert_called_once()
        assert [(account.value, account.display_name) for account in accounts] == [
            ("1111111", "Example Retail"),
            ("2222222", "2222222"),
        ]

    @parameterized.expand(
        [
            (
                "a key apple will not accept",
                AppleSearchAdsAuthError("Could not sign the Apple Ads client secret."),
                "Could not sign the Apple Ads client secret.",
            ),
            (
                "apple being unreachable",
                requests.ConnectionError("connection refused"),
                "Could not exchange the Apple Ads credentials for an access token",
            ),
        ]
    )
    def test_a_failed_token_exchange_becomes_a_listing_error(
        self, _name: str, raised: Exception, expected: str
    ) -> None:
        # The endpoint turns `IntegrationAccountListingError` into a 400 carrying its message and
        # lets everything else 500, so an auth failure that escapes as its own type shows someone
        # mid-setup an opaque server error instead of the reason their key was refused.
        with mock.patch(f"{SOURCE_MODULE}.AppleSearchAdsClient") as mock_client:
            mock_client.return_value.authenticate.side_effect = raised

            with pytest.raises(IntegrationAccountListingError) as error:
                self.source.get_credential_accounts(self.config, self.team_id)

        assert expected in str(error.value)

    def test_the_older_api_version_lists_nothing_without_calling_apple(self) -> None:
        # v5 scopes on an organization id, which Apple does show in its UI, so there is nothing to
        # list. The picker fires on every completed edit, so spending a token exchange to return an
        # empty list would burn the customer's Apple rate-limit budget for nothing.
        with mock.patch(f"{SOURCE_MODULE}.AppleSearchAdsClient") as mock_client:
            accounts = self.source.get_credential_accounts(
                self.config, self.team_id, api_version=APPLE_SEARCH_ADS_API_VERSION_V5
            )

        assert accounts == []
        mock_client.assert_not_called()
