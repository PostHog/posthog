from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia import AlgoliaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import (
    ALGOLIA_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.source import AlgoliaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AlgoliaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "records",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestAlgoliaSource:
    def setup_method(self) -> None:
        self.source = AlgoliaSource()
        self.team_id = 123
        self.config = AlgoliaSourceConfig(application_id="APPID", api_key="test-key", index_name="my_index")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ALGOLIA

    def test_application_id_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to the host derived from application_id, so changing
        # it must force the key to be re-entered.
        assert self.source.connection_host_fields == ["application_id"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Algolia"
        assert config.label == "Algolia"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/algolia.png"

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["application_id", "api_key", "index_name"]

        by_name = {f.name: f for f in fields}
        assert by_name["application_id"].type == SourceFieldInputConfigType.TEXT
        assert by_name["application_id"].secret is False
        assert by_name["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert by_name["api_key"].secret is True
        assert all(f.required for f in fields)

    @pytest.mark.parametrize("expected_key", ["403 Client Error", "401 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(expected_key in k for k in keys)

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No Algolia endpoint exposes a server-side updated-since filter, so every schema is
        # full refresh only.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_should_sync_defaults_match_settings(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name, endpoint in ALGOLIA_ENDPOINTS.items():
            assert schemas[name].should_sync_default == endpoint.should_sync_default

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["records"])
        assert len(schemas) == 1
        assert schemas[0].name == "records"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            ((False, "Invalid Algolia Application ID or API key"), False, "Invalid Algolia Application ID or API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.source.validate_algolia_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(
            application_id="APPID",
            api_key="test-key",
            index_name="my_index",
            schema_name=None,
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.source.validate_algolia_credentials"
    )
    def test_validate_credentials_passes_schema_name(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, schema_name="synonyms")

        assert mock_validate.call_args.kwargs["schema_name"] == "synonyms"

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AlgoliaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.algolia.source.algolia_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="synonyms", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            endpoint="synonyms",
            application_id="APPID",
            api_key="test-key",
            index_name="my_index",
            logger=inputs.logger,
            manager=manager,
        )

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        described = self.source.get_canonical_descriptions()
        assert set(described.keys()) == set(ENDPOINTS)
