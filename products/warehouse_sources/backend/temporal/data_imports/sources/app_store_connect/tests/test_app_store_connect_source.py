from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.app_store_connect import (
    APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR,
    APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR,
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
