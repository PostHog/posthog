from typing import Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.toast import ToastSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TOAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.source import ToastSource
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.toast import (
    TOAST_LOGIN_FAILED_MESSAGE,
    ToastResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

GUID = "aaaaaaaa-1111-2222-3333-444444444444"


def make_source_inputs(schema_name: str, **overrides: object) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = schema_name
    inputs.team_id = 1
    inputs.job_id = "job-1"
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = None
    for key, value in overrides.items():
        setattr(inputs, key, value)
    return inputs


class TestToastSource:
    def setup_method(self) -> None:
        self.source = ToastSource()
        self.team_id = 123
        self.config = ToastSourceConfig(
            client_id="client-id",
            client_secret="client-secret",
            restaurant_guids=GUID,
            environment="production",
            start_date="2024-01-01",
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TOAST

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Toast"
        assert config.label == "Toast"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/toast.png"

        input_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert input_names == ["client_id", "client_secret", "restaurant_guids", "start_date"]

        select_names = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert select_names == ["environment"]

    def test_client_secret_is_the_only_secret_field(self) -> None:
        fields = [f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)]
        secret_fields = [f for f in fields if f.secret]

        assert [f.name for f in secret_fields] == ["client_secret"]
        assert secret_fields[0].type == SourceFieldInputConfigType.PASSWORD
        assert secret_fields[0].required is True

    def test_only_the_start_date_is_optional(self) -> None:
        fields = [f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)]

        assert [f.name for f in fields if not f.required] == ["start_date"]

    def test_environment_options_match_the_hosts_the_transport_knows(self) -> None:
        select = next(f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldSelectConfig))

        assert [option.value for option in select.options] == ["production", "sandbox"]
        assert select.defaultValue == "production"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://ws-api.toasttab.com/authentication/v1/authentication/login",
            "403 Client Error: Forbidden for url: https://ws-api.toasttab.com/labor/v1/timeEntries",
            "403 Client Error: Forbidden for url: https://ws-sandbox-api.toasttab.com/orders/v2/ordersBulk",
            TOAST_LOGIN_FAILED_MESSAGE,
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://ws-api.toasttab.com/orders/v2/ordersBulk",
            "429 Client Error: Too Many Requests for url: https://ws-api.toasttab.com/orders/v2/ordersBulk",
        ],
    )
    def test_non_retryable_errors_leave_transient_failures_alone(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders", "shifts"])

        assert [schema.name for schema in schemas] == ["orders", "shifts"]

    @pytest.mark.parametrize("endpoint", sorted(TOAST_ENDPOINTS))
    def test_schema_metadata_matches_the_endpoint_settings(self, endpoint: str) -> None:
        settings = TOAST_ENDPOINTS[endpoint]
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is bool(settings.incremental_fields)
        assert schema.incremental_fields == settings.incremental_fields
        assert schema.detected_primary_keys == settings.primary_key
        assert schema.default_incremental_lookback_seconds == settings.default_incremental_lookback_seconds

    def test_only_endpoints_with_a_server_side_time_filter_are_incremental(self) -> None:
        assert set(INCREMENTAL_FIELDS) == {"orders", "time_entries", "shifts", "cash_entries", "deposits"}

    def test_tables_whose_rows_get_edited_cannot_be_appended(self) -> None:
        # Appending a corrected order would land a second copy of it instead of replacing the row.
        appendable = {s.name for s in self.source.get_schemas(self.config, self.team_id) if s.supports_append}

        assert appendable == {"cash_entries", "deposits"}

    def test_fan_out_primary_keys_include_the_restaurant(self) -> None:
        # Every row aggregates across locations, so a per-location guid alone can't key the table.
        fanned_out = [name for name, settings in TOAST_ENDPOINTS.items() if not settings.single_object]

        assert all("_restaurant_guid" in TOAST_ENDPOINTS[name].primary_key for name in fanned_out)

    def test_partition_keys_are_never_a_modified_timestamp(self) -> None:
        partition_keys = {s.partition_key for s in TOAST_ENDPOINTS.values() if s.partition_key}

        assert all("modified" not in key.lower() for key in partition_keys)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    def test_canonical_descriptions_are_exposed_by_the_source(self) -> None:
        assert self.source.get_canonical_descriptions() == CANONICAL_DESCRIPTIONS

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` walks a static catalog with no I/O, so the public docs can render the tables.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "result",
        [(True, None), (False, "Invalid Toast API credentials.")],
    )
    def test_validate_credentials_forwards_the_transport_result(self, result: tuple[bool, Optional[str]]) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.toast.source.validate_toast_credentials",
            return_value=result,
        ) as validate:
            assert self.source.validate_credentials(self.config, self.team_id) == result

        assert validate.call_args.args == ("production", "client-id", "client-secret", GUID)

    def test_get_resumable_source_manager_is_bound_to_the_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(make_source_inputs("orders"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ToastResumeConfig

    def test_source_for_pipeline_passes_the_watermark_when_syncing_incrementally(self) -> None:
        manager = mock.MagicMock()
        inputs = make_source_inputs(
            "orders", should_use_incremental_field=True, db_incremental_field_last_value="2024-05-01T00:00:00Z"
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.toast.source.toast_source"
        ) as toast_source_mock:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = toast_source_mock.call_args.kwargs
        assert kwargs["endpoint"] == "orders"
        assert kwargs["environment"] == "production"
        assert kwargs["restaurant_guids"] == GUID
        assert kwargs["start_date"] == "2024-01-01"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_the_watermark_on_a_full_refresh(self) -> None:
        inputs = make_source_inputs(
            "orders", should_use_incremental_field=False, db_incremental_field_last_value="2024-05-01T00:00:00Z"
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.toast.source.toast_source"
        ) as toast_source_mock:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert toast_source_mock.call_args.kwargs["db_incremental_field_last_value"] is None
