from datetime import date
from typing import Any, cast

from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads import (
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

    def test_the_connect_form_does_not_require_either_context_id(self) -> None:
        # `required` cannot express "depends on the version pin", so `validate_credentials`
        # enforces whichever one applies instead.
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig)
        }

        assert fields["ad_account_id"].required is False
        assert fields["org_id"].required is False
