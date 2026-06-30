from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly import source as rootly_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.rootly import RootlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.source import RootlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRootlySourceConfig:
    def test_source_type(self) -> None:
        assert RootlySource().source_type == ExternalDataSourceType.ROOTLY

    def test_config_basics(self) -> None:
        config = RootlySource().get_source_config
        assert config.label == "Rootly"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Ships hidden until end-to-end sync is verified against a live key.
        assert config.unreleasedSource is True

    def test_single_password_api_key_field(self) -> None:
        fields = RootlySource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.required is True
        assert field.type == SourceFieldInputConfigType.PASSWORD


class TestRootlyGetSchemas:
    def test_returns_every_endpoint(self) -> None:
        schemas = RootlySource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("incidents", True),
            ("alerts", True),
            ("action_items", True),
            ("post_mortems", True),
            ("pulses", True),
            ("users", False),
            ("teams", False),
            ("severities", False),
            ("workflows", False),
        ]
    )
    def test_incremental_support_matches_settings(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = {s.name: s for s in RootlySource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        # Incremental endpoints advertise updated_at/created_at; full-refresh ones advertise nothing.
        assert bool(schema.incremental_fields) is expected_incremental

    def test_pulses_off_by_default(self) -> None:
        # Pulses are the high-volume activity timeline, so they shouldn't sync unless opted in.
        schemas = {s.name: s for s in RootlySource().get_schemas(MagicMock(), team_id=1)}
        assert schemas["pulses"].should_sync_default is False
        assert schemas["incidents"].should_sync_default is True

    def test_names_filter(self) -> None:
        schemas = RootlySource().get_schemas(MagicMock(), team_id=1, names=["incidents", "users"])
        assert {s.name for s in schemas} == {"incidents", "users"}


class TestRootlyValidateCredentials:
    @parameterized.expand(
        [
            # (probe status, schema_name, expected_ok)
            ("ok", 200, None, True),
            ("ok_for_schema", 200, "incidents", True),
            # A 403 at source-create is a genuine token scoped away from the probe resource — accept it.
            ("forbidden_at_create_accepted", 403, None, True),
            # A 403 while configuring a specific schema means no access to that resource — reject.
            ("forbidden_for_schema_rejected", 403, "incidents", False),
            ("unauthorized_rejected", 401, None, False),
            ("connection_failure_rejected", None, None, False),
            ("unexpected_status_rejected", 500, None, False),
        ]
    )
    def test_status_mapping(
        self, _name: str, probe_status: int | None, schema_name: str | None, expected_ok: bool
    ) -> None:
        with mock.patch.object(rootly_source_module, "probe_credentials", return_value=probe_status):
            ok, error = RootlySource().validate_credentials(
                MagicMock(api_key="rootly_test"), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestRootlyNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.rootly.com/v1/incidents?page[size]=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.rootly.com/v1/secrets"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = RootlySource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.rootly.com/v1/incidents"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.rootly.com/v1/incidents"),
            ("read_timeout", "HTTPSConnectionPool(host='api.rootly.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = RootlySource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestRootlyResumableAndPipeline:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = RootlySource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RootlyResumeConfig

    def test_source_for_pipeline_plumbs_endpoint_and_keys(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "incidents"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        response = RootlySource().source_for_pipeline(
            MagicMock(api_key="rootly_test"), resumable_source_manager=MagicMock(), inputs=inputs
        )
        assert response.name == "incidents"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    @parameterized.expand(
        [
            # Endpoints partition on the stable created_at field...
            ("incidents", ["created_at"], "datetime"),
            ("users", ["created_at"], "datetime"),
            # ...except small enumeration resources whose timestamp columns aren't confirmed —
            # partitioning on an absent field would fail the sync, so they don't partition.
            ("environments", None, None),
            ("severities", None, None),
            ("incident_types", None, None),
            ("causes", None, None),
        ]
    )
    def test_partitioning_per_endpoint(
        self, endpoint: str, expected_keys: list[str] | None, expected_mode: str | None
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        response = RootlySource().source_for_pipeline(
            MagicMock(api_key="rootly_test"), resumable_source_manager=MagicMock(), inputs=inputs
        )
        assert response.partition_keys == expected_keys
        assert response.partition_mode == expected_mode


class TestRootlyCanonicalDescriptions:
    def test_descriptions_keyed_by_endpoint_name(self) -> None:
        descriptions = RootlySource().get_canonical_descriptions()
        # Every documented key must be a real endpoint so enrichment binds to the right table.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "incidents" in descriptions
        assert descriptions["incidents"]["columns"]["id"]
