from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.app_store_connect import (
    AppStoreConnectResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
    APP_STORE_CONNECT_ENDPOINTS,
    ENDPOINTS,
    REPORT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.source import (
    AppStoreConnectSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstoreconnect import (
    AppStoreConnectSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.source"


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
    def test_source_type(self) -> None:
        assert AppStoreConnectSource().source_type == ExternalDataSourceType.APPSTORECONNECT

    def test_source_is_visible_and_labelled_alpha(self) -> None:
        config = AppStoreConnectSource().get_source_config

        # `unreleasedSource` hides a source from users entirely; a finished source must not set it.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
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
            is_report = name in REPORT_ENDPOINTS
            # Apple exposes no server-side timestamp filter on the JSON:API collections, so only the
            # report streams (filtered by reportDate) can sync incrementally.
            assert schema.supports_incremental is is_report
            assert schema.should_sync_default is not is_report
            if is_report:
                assert [field["field"] for field in schema.incremental_fields] == ["report_date"]

    def test_canonical_descriptions_cover_the_catalog(self) -> None:
        descriptions = AppStoreConnectSource().get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for name in ENDPOINTS:
            assert descriptions[name].get("description")
            assert descriptions[name].get("columns")

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

    def test_resumable_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = AppStoreConnectSource().get_resumable_source_manager(MagicMock())

        assert manager._data_class is AppStoreConnectResumeConfig

    def test_source_for_pipeline_plumbs_credentials_and_the_watermark(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "sales_reports"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-01"
        manager = MagicMock()

        with patch(f"{SOURCE_MODULE}.app_store_connect_source") as mocked:
            AppStoreConnectSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = mocked.call_args.kwargs
        assert kwargs["issuer_id"] == "57246542-96fe-1a63-e053-0824d011072a"
        assert kwargs["key_id"] == "2X9R4HXF34"
        assert kwargs["vendor_number"] == "85234567"
        assert kwargs["endpoint"] == "sales_reports"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-03-01"

    def test_full_refresh_run_does_not_pass_a_watermark(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "apps"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-03-01"

        with patch(f"{SOURCE_MODULE}.app_store_connect_source") as mocked:
            AppStoreConnectSource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_auth_and_permission_failures_are_non_retryable(self) -> None:
        errors = cast(dict[str, Any], AppStoreConnectSource().get_non_retryable_errors())

        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        assert all(message for message in errors.values())
