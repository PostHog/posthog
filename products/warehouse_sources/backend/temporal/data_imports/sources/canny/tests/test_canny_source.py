from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny import CannyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.source import CannySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CannySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "posts",
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


class TestCannySource:
    def setup_method(self) -> None:
        self.source = CannySource()
        self.team_id = 123
        self.config = CannySourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CANNY

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Canny"
        assert config.label == "Canny"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Canny ships hidden for now — it must stay behind unreleasedSource until released.
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/canny.png"

        assert len(config.fields) == 1
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "invalid API key",
            "401 Client Error: Unauthorized for url: https://canny.io",
            "403 Client Error: Forbidden for url: https://canny.io",
        ],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Canny exposes no server-side updated-since filter, so every stream is full refresh only.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["posts"])
        assert len(schemas) == 1
        assert schemas[0].name == "posts"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Canny API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canny.source.validate_canny_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CannyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.canny.source.canny_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="comments", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            endpoint="comments",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Every advertised endpoint should carry a curated description so the warehouse can describe
        # it deterministically instead of paying for per-team LLM enrichment.
        assert set(ENDPOINTS).issubset(descriptions.keys())
        assert all(entry.get("description") for entry in descriptions.values())
