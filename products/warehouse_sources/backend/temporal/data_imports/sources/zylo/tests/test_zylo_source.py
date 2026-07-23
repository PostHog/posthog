import pytest
from unittest import mock
from unittest.mock import MagicMock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zylo import ZyloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source import ZyloSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.zylo import ZyloResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestZyloSource:
    def setup_method(self) -> None:
        self.source = ZyloSource()
        self.team_id = 123
        self.config = ZyloSourceConfig(token_id="tok_id", token_secret="tok_secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ZYLO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Zylo"
        assert config.label == "Zylo"
        assert config.releaseStatus == "alpha"
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/zylo.png"
        assert len(config.fields) == 2

        token_id_field, token_secret_field = config.fields
        assert isinstance(token_id_field, SourceFieldInputConfig)
        assert token_id_field.name == "token_id"
        assert token_id_field.type == SourceFieldInputConfigType.TEXT
        assert token_id_field.required is True
        assert token_id_field.secret is False

        assert isinstance(token_secret_field, SourceFieldInputConfig)
        assert token_secret_field.name == "token_secret"
        assert token_secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_secret_field.required is True
        assert token_secret_field.secret is True

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_all_support_incremental(self, endpoint: str) -> None:
        # Every Zylo resource exposes zylo_created_at/zylo_modified_at as genuine server-side filters.
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        fields = {f["field"] for f in schema.incremental_fields}
        assert fields == {"zylo_created_at", "zylo_modified_at"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Applications"])
        assert len(schemas) == 1
        assert schemas[0].name == "Applications"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Zylo credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source.validate_zylo_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("tok_id", "tok_secret")

    @pytest.mark.parametrize(
        "config",
        [
            ZyloSourceConfig(token_id="", token_secret="tok_secret"),
            ZyloSourceConfig(token_id="tok_id", token_secret=""),
        ],
    )
    def test_validate_credentials_requires_both_fields(self, config: ZyloSourceConfig) -> None:
        is_valid, error_message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert error_message == "Zylo token ID and token secret are required"

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url",
            "403 Client Error: Forbidden for url",
        ],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        ("status", "expected_message"),
        [
            (200, None),
            (429, None),
            (500, None),
            (401, "API key is invalid"),
            (403, "API key is missing the `applications:read and spend:read` permission scope"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source.probe_endpoint_status")
    def test_get_endpoint_permissions(
        self, mock_probe: MagicMock, status: int | None, expected_message: str | None
    ) -> None:
        mock_probe.return_value = status

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["PurchaseOrders"])

        assert permissions == {"PurchaseOrders": expected_message}

    def test_get_endpoint_permissions_unknown_endpoint_is_reachable(self) -> None:
        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["NotARealEndpoint"])
        assert permissions == {"NotARealEndpoint": None}

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZyloResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source.zylo_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_zylo_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Contracts"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "zylo_modified_at"
        inputs.db_incremental_field_last_value = "2024-01-01"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_zylo_source.assert_called_once_with(
            token_id="tok_id",
            token_secret="tok_secret",
            endpoint="Contracts",
            team_id=7,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="zylo_modified_at",
            db_incremental_field_last_value="2024-01-01",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source.zylo_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_zylo_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Applications"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        inputs.db_incremental_field_last_value = "2024-01-01"

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_zylo_source.call_args.kwargs["db_incremental_field_last_value"] is None
