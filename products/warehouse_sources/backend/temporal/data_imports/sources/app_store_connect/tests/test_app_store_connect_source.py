from typing import Any, cast

from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.app_store_connect import (
    APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR,
    APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR,
    APP_STORE_CONNECT_MISSING_VENDOR_NUMBER_ERROR,
    APP_STORE_CONNECT_READ_FORBIDDEN_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
    APP_STORE_CONNECT_ENDPOINTS,
    ENDPOINTS,
    REPORT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.source import (
    AppStoreConnectSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstoreconnect import (
    AppStoreConnectSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.source"


def _resolve_friendly_error(error_message: str) -> str | None:
    # Mirrors external_data_job: the first matching key's friendly message is the one shown.
    errors = AppStoreConnectSource().get_non_retryable_errors()
    for key, friendly in errors.items():
        if error_message_matches(error_message, [key]):
            return friendly
    return None


def _config(vendor_number: str | None = "85234567") -> AppStoreConnectSourceConfig:
    return AppStoreConnectSourceConfig(
        issuer_id="57246542-96fe-1a63-e053-0824d011072a",
        key_id="2X9R4HXF34",
        private_key="-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----",
        vendor_number=vendor_number,
    )


def _input_fields(source: AppStoreConnectSource) -> dict[str, SourceFieldInputConfig]:
    return {
        field.name: field
        for field in source.get_source_config.fields or []
        if isinstance(field, SourceFieldInputConfig)
    }


class TestAppStoreConnectSource:
    def test_source_is_visible_and_labelled_beta(self) -> None:
        config = AppStoreConnectSource().get_source_config

        # `unreleasedSource` hides a source from users entirely; a finished source must not set it.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.BETA
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.docsUrl is not None

    @parameterized.expand(
        [
            ("issuer_id", SourceFieldInputConfigType.TEXT, True, False),
            ("key_id", SourceFieldInputConfigType.TEXT, True, False),
            ("private_key", SourceFieldInputConfigType.TEXTAREA, True, True),
            ("vendor_number", SourceFieldInputConfigType.TEXT, False, False),
        ]
    )
    def test_credential_fields(
        self, name: str, field_type: SourceFieldInputConfigType, required: bool, secret: bool
    ) -> None:
        field = _input_fields(AppStoreConnectSource())[name]

        assert field.type == field_type
        assert field.required is required
        assert field.secret is secret

    def test_get_schemas_returns_the_whole_catalog_with_its_keys(self) -> None:
        schemas = AppStoreConnectSource().get_schemas(_config(), team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        for schema in schemas:
            assert schema.detected_primary_keys == APP_STORE_CONNECT_ENDPOINTS[schema.name].primary_keys

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = AppStoreConnectSource().get_schemas(_config(), team_id=1, names=["customer_reviews"])

        assert [schema.name for schema in schemas] == ["customer_reviews"]

    def test_only_report_tables_are_incremental_and_opt_in(self) -> None:
        schemas = {schema.name: schema for schema in AppStoreConnectSource().get_schemas(_config(), team_id=1)}

        for name, schema in schemas.items():
            kind = APP_STORE_CONNECT_ENDPOINTS[name].kind
            is_report_stream = kind in ("sales_report", "analytics_report")
            # Apple exposes no server-side timestamp filter on the JSON:API collections, so only the
            # report streams (walked by report date or instance processing date) sync incrementally.
            assert schema.supports_incremental is is_report_stream
            assert schema.should_sync_default is not is_report_stream
            if kind == "sales_report":
                assert [field["field"] for field in schema.incremental_fields] == ["report_date"]
            if kind == "analytics_report":
                assert [field["field"] for field in schema.incremental_fields] == ["processing_date"]

    @parameterized.expand(
        [
            ("analytics_app_sessions_detailed", "analytics_app_sessions"),
            ("analytics_app_store_downloads_detailed", "analytics_app_store_downloads"),
            ("analytics_installations_deletions_detailed", "analytics_installations_deletions"),
            ("analytics_discovery_engagement_detailed", "analytics_discovery_engagement"),
        ]
    )
    def test_detailed_analytics_streams_extend_their_standard_siblings(self, detailed: str, standard: str) -> None:
        source = AppStoreConnectSource()

        assert detailed in {schema.name for schema in source.get_schemas(_config(), team_id=1)}
        # Apple files both variants of a report under the same category; a mismatch would make the
        # per-request report list come back empty and the table sync nothing, without an error.
        assert (
            APP_STORE_CONNECT_ENDPOINTS[detailed].analytics_report_category
            == APP_STORE_CONNECT_ENDPOINTS[standard].analytics_report_category
        )

        descriptions = source.get_canonical_descriptions()
        # A Detailed report is its Standard sibling plus exactly the three acquisition
        # attribution columns Apple publishes in no Standard report.
        assert set(descriptions[detailed]["columns"]) == set(descriptions[standard]["columns"]) | {
            "campaign",
            "page_title",
            "source_info",
        }

    def test_report_tables_need_a_vendor_number_in_the_picker(self) -> None:
        permissions = AppStoreConnectSource().get_endpoint_permissions(
            _config(vendor_number=None), team_id=1, endpoints=list(ENDPOINTS)
        )

        assert [name for name, reason in permissions.items() if reason is not None] == list(REPORT_ENDPOINTS)

    def test_all_tables_are_reachable_once_a_vendor_number_is_set(self) -> None:
        permissions = AppStoreConnectSource().get_endpoint_permissions(_config(), team_id=1, endpoints=list(ENDPOINTS))

        assert set(permissions.values()) == {None}

    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("server_error", 500, None, False),
            ("unreachable", None, None, False),
            ("bad_private_key", None, "bad key", False),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status: int | None, message: str | None, expected_valid: bool
    ) -> None:
        with patch(f"{SOURCE_MODULE}.check_credentials", return_value=(status, message)):
            valid, error = AppStoreConnectSource().validate_credentials(_config(), team_id=1)

        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_forbidden_is_accepted_at_source_create_but_not_per_schema(self) -> None:
        source = AppStoreConnectSource()

        with patch(f"{SOURCE_MODULE}.check_credentials", return_value=(403, None)):
            created, create_error = source.validate_credentials(_config(), team_id=1)
            per_schema, schema_error = source.validate_credentials(_config(), team_id=1, schema_name="builds")

        # A key whose role can't read `/v1/apps` is still a real key, so source creation must not fail.
        assert (created, create_error) == (True, None)
        assert per_schema is False
        assert schema_error is not None

    def test_report_schema_without_a_vendor_number_fails_before_probing(self) -> None:
        with patch(f"{SOURCE_MODULE}.check_credentials") as mocked:
            valid, error = AppStoreConnectSource().validate_credentials(
                _config(vendor_number=None), team_id=1, schema_name="sales_reports"
            )

        assert valid is False
        assert error is not None and "vendor number" in error
        mocked.assert_not_called()

    def test_missing_vendor_number_is_non_retryable(self) -> None:
        # A report sync raises this ValueError when no vendor number is set. It can never succeed on
        # retry, so the source must classify it non-retryable rather than burn the activity's budget.
        friendly = _resolve_friendly_error(APP_STORE_CONNECT_MISSING_VENDOR_NUMBER_ERROR)

        assert friendly is not None

    def test_auth_and_permission_failures_are_non_retryable(self) -> None:
        errors = cast(dict[str, Any], AppStoreConnectSource().get_non_retryable_errors())

        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        assert all(message for message in errors.values())

    @parameterized.expand(
        [
            ("analytics_create", APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR),
            ("analytics_inactive", APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR),
            ("read", APP_STORE_CONNECT_READ_FORBIDDEN_ERROR),
        ]
    )
    def test_each_forbidden_case_resolves_to_its_own_copy(self, _name: str, constant: str) -> None:
        # The source raises `<constant> (Apple said: ... (HTTP 403))`; the mapping must resolve each
        # distinct case to its own copy, so the analytics create and inactivity cases never inherit
        # the read wording that names Finance or Sales — the roles the failing key already holds.
        raised = f"{constant} (Apple said: FORBIDDEN_ERROR (HTTP 403))"

        friendly = _resolve_friendly_error(raised)

        assert friendly == constant
        if constant is not APP_STORE_CONNECT_READ_FORBIDDEN_ERROR:
            assert friendly is not None
            assert "Finance" not in friendly and "Sales" not in friendly

    @parameterized.expand(
        [
            (
                "connection_error",
                "HTTPSConnectionPool(host='api.appstoreconnect.apple.com', port=443): Max retries exceeded "
                'with url: /v1/apps?limit=200 (Caused by ReadTimeoutError("HTTPSConnectionPool'
                "(host='api.appstoreconnect.apple.com', port=443): Read timed out. (read timeout=60)\"))",
            ),
            (
                "read_timeout",
                "HTTPSConnectionPool(host='api.appstoreconnect.apple.com', port=443): Read timed out. (read timeout=60)",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.appstoreconnect.apple.com/v1/salesReports?filter%5Bfrequency%5D=DAILY",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.appstoreconnect.apple.com/v1/salesReports",
            ),
        ]
    )
    def test_retryable_errors_match_transient_network_failures(self, _name: str, observed_error: str) -> None:
        # `_get` has no retry loop of its own — it relies on the tracked session's urllib3 adapter.
        # Once that's exhausted, this keeps the benign, self-recovering failure out of error tracking.
        retryable_errors = AppStoreConnectSource().get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)
